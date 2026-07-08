#include <sys/epoll.h>
#include <sys/socket.h>
#include <sys/timerfd.h>
#include <sys/types.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
#include <errno.h>
#include <signal.h>
#include <assert.h>
#include <sys/timex.h>

#define DEBUG
#ifdef DEBUG
#define debug_printf(...) fprintf(stderr, __VA_ARGS__)
#else
#define debug_printf(...)   /* do nothing */
#endif

#define MAX_EPOLL_EVENTS    32
#define SYNC_MSG_LEN        strlen("SYNC A\n")
#define NSEC_PER_SEC        1000000000L

/* This code implements the server side of the walt clock synchronization
 * protocol used by nodes at boot time (see walt-clock-sync on node side):
 * 1- the node opens a TCP connection and sends a "SYNC a\n" (adjtime)
 *    or "SYNC b\n" (basic, clock offset only) message
 * 2- the server computes the one-way-delay (owd) to this node, using the
 *    RTT estimate provided by the kernel through getsockopt(TCP_INFO),
 *    divided by two
 * 3- the server plans to answer at the next second boundary of its own
 *    clock, minus this one-way-delay, so that the message reaches the node
 *    right when the server clock reaches this second boundary
 * 4- at the planned time, the server sends this integer value as text,
 *    and the frequency offset to apply ('a' mode only), then closes
 *    the connection
 * Nodes may only be able to set their own clock with a 1-second resolution
 * (e.g. busybox date), hence the integer value.
 *
 * This code may serve many nodes concurrently (e.g., a batch of nodes
 * booting at the same time). Instead of maintaining our own list of
 * pending wakeup times and computing a millisecond-granularity timeout
 * for epoll_wait() (which would only offer 1ms resolution and require an
 * explicit sorted structure), we let the kernel do this work for us:
 * each client waiting for its answer to be sent gets its own timerfd(7),
 * armed with the exact absolute wakeup time (nanosecond resolution,
 * CLOCK_REALTIME, TFD_TIMER_ABSTIME). This timerfd is then simply added
 * to the same epoll set as the client sockets. This considerably
 * simplifies the code: epoll_wait() can always be called with an infinite
 * timeout, and firing exactly at the right time for each client is
 * entirely delegated to the kernel.
 */

typedef enum {
    ST_IDLE = 0,               /* initial state */
    ST_WAIT_SEND_SYNC = 1,     /* wait before sending the first SYNC */
    ST_WAIT_SEND_ADJTIME = 2,  /* wait before sending ADJTIME */
    ST_WAIT_RECV_ADJTIME = 3,  /* wait before receiving ADJTIME info */
} client_state_t;

typedef struct client {
    int sock_fd;
    int timer_fd;              /* -1 until armed */
    client_state_t state;
    char rbuf[SYNC_MSG_LEN];
    int rbuf_len;
    long clock_ts;             /* integer value (unix timestamp) to send */
} client_t;

/* fd -> client_t* table, indexed by fd value (fds are small integers).
 * Both a client's sock_fd and (once created) its timer_fd are recorded
 * here, pointing to the very same client_t. */
static client_t **clients = NULL;
static int clients_cap = 0;

static int epfd = -1;

static struct sigaction old_sigact;
static enum {
    RUNNING,
    STOPPED
} status;

static void handle_signal(int sig) {
    /* restore initial signal handler (the one installed by python) */
    sigaction(SIGINT, &old_sigact, NULL);
    /* let python handle the signal (schedule a KeyboardInterrupt) */
    raise(sig);
    /* let our loop know it should stop, so we return to python code, which
     * will let it actually raise this KeyboardInterrupt exception. */
    status = STOPPED;
}

static void redirect_sigint() {
    struct sigaction sigact;
    sigact.sa_handler = handle_signal;
    sigemptyset(&sigact.sa_mask);
    sigact.sa_flags = SA_NODEFER;  /* needed to re-raise signal in its own handler */
    sigaction(SIGINT, &sigact, &old_sigact);
}

static void *malloc_or_abort(size_t size) {
    void *res = malloc(size);
    if (res == NULL) {
        perror("malloc");
        exit(1);
    }
    return res;
}

static void *realloc_or_abort(void *ptr, size_t size) {
    void *res = realloc(ptr, size);
    if (res == NULL) {
        perror("realloc");
        exit(1);
    }
    return res;
}

static void set_client_at(int fd, client_t *client) {
    if (fd >= clients_cap) {
        int new_cap = clients_cap == 0 ? 64 : clients_cap;
        while (fd >= new_cap) {
            new_cap *= 2;
        }
        clients = realloc_or_abort(clients, new_cap * sizeof(client_t *));
        memset(clients + clients_cap, 0,
               (new_cap - clients_cap) * sizeof(client_t *));
        clients_cap = new_cap;
    }
    clients[fd] = client;
}

static inline client_t *get_client_at(int fd) {
    if (fd < 0 || fd >= clients_cap) {
        return NULL;
    }
    return clients[fd];
}

static void set_nonblocking(int fd) {
    int flags = fcntl(fd, F_GETFL, 0);
    fcntl(fd, F_SETFL, flags | O_NONBLOCK);
}

static void register_fd(int fd) {
    struct epoll_event ev;
    ev.events = EPOLLIN;
    ev.data.fd = fd;
    if (epoll_ctl(epfd, EPOLL_CTL_ADD, fd, &ev) != 0) {
        perror("epoll_ctl(ADD)");
        abort();
    }
}

static inline void unregister_fd(int fd) {
    epoll_ctl(epfd, EPOLL_CTL_DEL, fd, NULL);
}

static inline void register_client_fd(client_t *client, int fd) {
    set_client_at(fd, client);
    register_fd(fd);
}

static inline void unregister_client_fd(client_t *client, int fd) {
    unregister_fd(fd);
    set_client_at(fd, NULL);
}

static void cleanup_timer(client_t *client) {
    unregister_client_fd(client, client->timer_fd);
    close(client->timer_fd);
    client->timer_fd = -1;
}

static inline void consume_timer(client_t *client) {
    uint64_t nb_expirations;
    /* we must read the timerfd to acknowledge the event, even though we
     * are about to close it anyway right after. */
    (void)!read(client->timer_fd, &nb_expirations, sizeof(nb_expirations));
}

static void cleanup_client(client_t *client) {
    if (client->timer_fd >= 0) {
        cleanup_timer(client);
    }
    unregister_client_fd(client->sock_fd);
    close(client->sock_fd);
    free(client);
}

/* returns the RTT estimate in microseconds, or -1 if it could not be
 * retrieved */
static long get_rtt_us(int fd) {
    struct tcp_info tcp_info;
    socklen_t optlen = sizeof(tcp_info);
    if (getsockopt(fd, IPPROTO_TCP, TCP_INFO, &tcp_info, &optlen) != 0) {
        perror("getsockopt");
        abort();
    }
    return (long)tcp_info.tcpi_rtt;
}

/* subtract a given number of nanoseconds (>= 0) from a timespec, using
 * plain integer arithmetic only */
static void ts_sub_ns(struct timespec *ts, long ns) {
    while (ns >= NSEC_PER_SEC) {
        /* highly unlikely */
        ts->tv_sec -= 1;
        ns -= NSEC_PER_SEC;
    }
    if (ns > ts->tv_nsec) {
        /* unlikely */
        ts->tv_sec -= 1;
        ts->tv_nsec += NSEC_PER_SEC - ns;
    }
    else {
        /* likely */
        ts->tv_nsec -= ns;
    }
}

static inline int ts_cmp(const struct timespec *a, const struct timespec *b) {
    if (a->tv_sec != b->tv_sec) {
        return (a->tv_sec < b->tv_sec) ? -1 : 1;
    }
    if (a->tv_nsec != b->tv_nsec) {
        return (a->tv_nsec < b->tv_nsec) ? -1 : 1;
    }
    return 0;
}

static void create_timer(client_t *client) {
    int tfd;

    tfd = timerfd_create(CLOCK_REALTIME, TFD_NONBLOCK);
    if (tfd < 0) {
        perror("timerfd_create");
        abort();
    }
    client->timer_fd = tfd;
}

static void arm_timer_at(client_t *client, struct timespec *ts) {
    struct itimerspec its;

    memset(&its, 0, sizeof(its));
    its.it_value = *ts;   /* it_interval left at 0: one-shot timer */
    if (timerfd_settime(tfd, TFD_TIMER_ABSTIME, &its, NULL) != 0) {
        perror("timerfd_settime");
        abort();
    }
}

static void send_message(client_t *client, char *fmt, ...) {
    int off = 0;
    int retries_left = 1000;
    va_list ap;
    char msg[32];
    int len;

    va_start(ap, fmt);
    len = vsnprintf(msg, sizeof(msg), fmt, ap);
    va_end(ap);

    /* the messages are tiny (a handful of bytes) and the socket send buffer
     * is virtually never full in this scenario, so a simple retry loop is
     * enough; we bound retries so that a stuck/broken client can never
     * cause us to loop indefinitely. */
    while (off < len && retries_left > 0) {
        ssize_t n = write(client->sock_fd, msg + off, len - off);
        if (n > 0) {
            off += n;
            continue;
        }
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            retries_left--;
            usleep(1000);
            continue;
        }
        if (n < 0 && errno == EINTR) {
            continue;
        }
        break;  /* other error, give up sending to this client */
    }
}

static void plan_sync_msg(client_t *client) {
    long rtt_us, owd_ns;
    struct timespec now, target;
    long clock_ts;
    int tfd;
    struct epoll_event ev;

    /* The client's tooling only supports setting the date
     * as an integer epoch number, so we wait for the next
     * second boundary. We take the one-way-delay into account:
     * we send the message slightly earlier so that the client
     * receives it at the right time. */
    rtt_us = get_rtt_us(client->sock_fd);
    /* rtt (us) -> owd (ns) */
    owd_ns = (rtt_us / 2) * 1000L;

    clock_gettime(CLOCK_REALTIME, &now);
    clock_ts = now.tv_sec + 1;
    target.tv_sec = clock_ts;
    target.tv_nsec = 0;
    ts_sub_ns(&target, owd_ns);
    if (ts_cmp(&now, &target) >= 0) {
        /* too late for this second boundary, target the next one */
        clock_ts += 1;
        target.tv_sec = clock_ts;
        target.tv_nsec = 0;
        ts_sub_ns(&target, owd_ns);
    }

    client->clock_ts = clock_ts;
    arm_timer_at(client, &target);
    debug_printf("client fd=%d: rtt=%ldus owd=%ldns clock_ts=%ld\n",
                 client->sock_fd, rtt_us, owd_ns, clock_ts);
}

int parse_bb_adjtimex_output(const char *input, struct timex *result) {
    int mask_found = 0;

    char *saveptr;
    for (char *line = strtok_r(input, "\n", &saveptr); line;
         line = strtok_r(NULL, "\n", &saveptr)) {

        // Skip leading whitespace
        while (isspace(*line)) line++;

        char *colon = strchr(line, ':');
        if (!colon) continue;

        char *value = colon + 1;
        while (isspace(*value)) value++;

        if (strstr(line, "offset:")) {
            result->offset = strtol(value, NULL, 10);
            mask_found += 1;
        } else if (strstr(line, "freq.adjust:")) {
            result->freq = strtol(value, NULL, 10);
            mask_found += 2;
        } else if (strstr(line, "status:")) {
            result->status = strtol(value, NULL, 10);
            mask_found += 4;
        } else if (strstr(line, "time.tv_sec:")) {
            result->time.tv_sec = strtol(value, NULL, 10);
            mask_found += 8;
        } else if (strstr(line, "time.tv_usec:")) {
            result->time.tv_usec = strtol(value, NULL, 10);
            mask_found += 16;
        }
    }

    if (mask_found != 31) {
        fprintf(stderr, "Could not parse adjtime data successfully!\n");
        return 1;
    }

    if (!(result->status & STA_NANO)) {
        result->time.tv_usec *= 1000L;  /* was in microseconds */
    }

    return 0;
}

int read_until_double_newline(int fd, char *buf, int buflen) {
    size_t total = 0;
    ssize_t n;

    while (total < buflen) {
        n = read(fd, buf + total, buflen - total);
        if (n <= 0) {
            return -1;
        }
        total += n;

        char *found = strstr(buf, "\n\n");
        if (found) {
            return found - buf;
        }
    }
    return -1;
}

static int handle_adjtime_response(client_t *client) {
    struct timex data;
    char buf[1024];
    int msg_size;

    msg_size = read_until_double_newline(client->sock_fd, buf, 1024);
    if (msg_size == -1) {
        return -1;
    }

    buf[msg_size] = '\0';
    if (parse_bb_adjtimex_output(buf, &data) != 0) {
        return -1;
    }

    printf("Offset: %ld\n", data.offset);
    printf("Freq adjust: %ld\n", data.freq);
    printf("Status: %d\n", data.status);
    printf("Time sec: %ld\n", data.time.tv_sec);
    printf("Time usec: %ld\n", data.time.tv_usec);

    return 0;
}

/* accept as many pending incoming connections as possible on the listening
 * socket */
static void accept_new_clients(int listen_fd) {
    for (;;) {
        int fd = accept(listen_fd, NULL, NULL);
        client_t *client;
        struct epoll_event ev;
        if (fd < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                return;
            }
            if (errno == EINTR) {
                continue;
            }
            /* unexpected error, ignore and keep serving other clients */
            return;
        }
        client = malloc_or_abort(sizeof(client_t));
        memset(client, 0, sizeof(client_t));
        client->sock_fd = fd;
        register_client_fd(client, fd);
        create_timer(client);
        plan_sync_msg(client);
        client->state = ST_WAIT_SEND_SYNC;
    }
}

void _clock_syncd_main_loop(int listen_fd) {
    struct epoll_event ev, events[MAX_EPOLL_EVENTS];

    epfd = epoll_create1(0);
    if (epfd < 0) {
        perror("epoll_create1");
        exit(1);
    }
    set_nonblocking(listen_fd);
    register_fd(listen_fd);

    redirect_sigint();

    status = RUNNING;
    while (status == RUNNING) {
        /* no manual timeout computation needed: each pending client has
         * its own timerfd in the same epoll set, so we can always block
         * indefinitely here; the kernel wakes us up exactly when needed. */
        int n = epoll_wait(epfd, events, MAX_EPOLL_EVENTS, -1);
        if (n < 0) {
            if (errno == EINTR) {
                /* either our signal handler requested a stop (status is
                 * now STOPPED, loop condition will end it), or some other
                 * signal interrupted us for no reason we should care
                 * about; just loop again in both cases. */
                continue;
            }
            perror("epoll_wait");
            break;
        }
        for (int i = 0; i < n; i++) {
            int fd = events[i].data.fd;
            if (fd == listen_fd) {
                accept_new_clients(listen_fd);
                continue;
            }
            client_t *client = get_client_at(fd);
            if (client == NULL) {
                continue;   /* stale event, ignore */
            }
            if (fd == client->timer_fd) {
                /* the timer fired */
                consume_timer(client);
                switch (client->state) {
                    case ST_WAIT_SEND_SYNC:
                        /* send the SYNC message */
                        send_message(client, "SYNC %ld\n", client->clock_ts);
                        /* prepare sending the first adjtime */
                        arm_timer_delay(client, 5);
                        client->state = ST_WAIT_SEND_ADJTIME;
                        break;
                    case ST_WAIT_SEND_ADJTIME:
                        /* send ADJTIME info request */
                        send_message(client, "ADJTIME\n");
                        client->state = ST_WAIT_RECV_ADJTIME;
                        break;
                }
                continue;
            }
            /* otherwise this event is about client->sock_fd */
            if (events[i].events & (EPOLLHUP | EPOLLERR)) {
                cleanup_client(client);
                continue;
            }
            if (client->state == ST_WAIT_RECV_ADJTIME) {
                if (handle_adjtime_response(client) != 0) {
                    cleanup_client(client);
                }
            }
            else {
                /* we do not expect client input */
                cleanup_client(client);
            }
        }
    }

    /* cleanup: close all remaining client connections */
    for (int fd = 0; fd < clients_cap; fd++) {
        client_t *client = clients[fd];
        /* a client is recorded twice in the table (sock_fd and timer_fd),
         * only clean it up once, when reached through its sock_fd entry */
        if (client != NULL && fd == client->sock_fd) {
            cleanup_client(client);
        }
    }
    free(clients);
    clients = NULL;
    clients_cap = 0;
    close(epfd);
    epfd = -1;
}
