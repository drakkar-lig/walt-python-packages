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

//#define DEBUG
#ifdef DEBUG
#define debug_printf(...) fprintf(stderr, __VA_ARGS__)
#else
#define debug_printf(...)   /* do nothing */
#endif

#define MAX_EPOLL_EVENTS    32
#define SYNC_MSG            "SYNC\n"
#define SYNC_MSG_LEN        5
#define NSEC_PER_SEC        1000000000L

/* This code implements the server side of the walt clock synchronization
 * protocol used by nodes at boot time (see walt-clock-sync on node side):
 * 1- the node opens a TCP connection and sends a "SYNC\n" message
 * 2- the server computes the one-way-delay (owd) to this node, using the
 *    RTT estimate provided by the kernel through getsockopt(TCP_INFO),
 *    divided by two
 * 3- the server plans to answer at the next second boundary of its own
 *    clock, minus this one-way-delay, so that the message reaches the node
 *    right when the server clock reaches this second boundary
 * 4- at the planned time, the server sends this integer value as text,
 *    then closes the connection
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
    ST_WAIT_SYNC_MSG = 0,   /* waiting to receive "SYNC\n" */
    ST_WAIT_SEND_TIME = 1   /* timerfd created and armed, waiting for it
                               to fire so we can send the answer */
} client_state_t;

typedef struct client {
    int sock_fd;
    int timer_fd;              /* -1 until armed */
    client_state_t state;
    char rbuf[SYNC_MSG_LEN];
    int rbuf_len;
    long clock_ts;              /* integer value (unix timestamp) to send */
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

static void cleanup_client(client_t *client) {
    if (client->timer_fd >= 0) {
        epoll_ctl(epfd, EPOLL_CTL_DEL, client->timer_fd, NULL);
        set_client_at(client->timer_fd, NULL);
        close(client->timer_fd);
    }
    epoll_ctl(epfd, EPOLL_CTL_DEL, client->sock_fd, NULL);
    set_client_at(client->sock_fd, NULL);
    close(client->sock_fd);
    free(client);
}

/* returns the RTT estimate in microseconds, or -1 if it could not be
 * retrieved */
static long get_rtt_us(int fd) {
    unsigned char buf[256];
    socklen_t optlen = sizeof(buf);
    uint32_t tcpi_rtt;
    /* struct tcp_info layout (see linux/tcp.h): 8 bytes of small (u8)
     * fields, then a series of u32 fields; tcpi_rtt is the 16th u32 field
     * (0-indexed: 15), thus at byte offset 8 + 15*4 = 68.
     * We read it as raw bytes (instead of relying on a full local
     * definition of struct tcp_info, which may slightly differ across
     * kernel versions) to stay robust, similar to what is done on the
     * python side when this protocol was first prototyped. */
    if (getsockopt(fd, IPPROTO_TCP, TCP_INFO, buf, &optlen) != 0) {
        return -1;
    }
    if (optlen < 68 + 4) {
        return -1;
    }
    memcpy(&tcpi_rtt, buf + 68, sizeof(tcpi_rtt));
    return (long)tcpi_rtt;
}

/* subtract a given number of nanoseconds (>= 0) from a timespec, using
 * plain integer arithmetic only */
static void ts_sub_ns(struct timespec *ts, long ns) {
    ts->tv_sec -= ns / NSEC_PER_SEC;
    ts->tv_nsec -= ns % NSEC_PER_SEC;
    if (ts->tv_nsec < 0) {
        ts->tv_nsec += NSEC_PER_SEC;
        ts->tv_sec -= 1;
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

/* handle a just-received "SYNC\n" message: compute the timing and arm a
 * timerfd for this client, so that it fires exactly at the right time */
static void handle_sync_msg(client_t *client) {
    long rtt_us, owd_ns;
    struct timespec now, target;
    long clock_ts;
    int tfd;
    struct itimerspec its;
    struct epoll_event ev;

    rtt_us = get_rtt_us(client->sock_fd);
    if (rtt_us < 0) {
        rtt_us = 0;  /* could not retrieve rtt, fall back to no compensation */
    }
    /* rtt (us) -> owd (ns): / 2 * 1000 ; done with plain integers, no
     * floating point (and thus no libm dependency) needed. */
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

    tfd = timerfd_create(CLOCK_REALTIME, TFD_NONBLOCK);
    if (tfd < 0) {
        perror("timerfd_create");
        return;   /* give up on this client, it will just time out */
    }
    memset(&its, 0, sizeof(its));
    its.it_value = target;   /* it_interval left at 0: one-shot timer */
    if (timerfd_settime(tfd, TFD_TIMER_ABSTIME, &its, NULL) != 0) {
        perror("timerfd_settime");
        close(tfd);
        return;
    }

    client->clock_ts = clock_ts;
    client->timer_fd = tfd;
    client->state = ST_WAIT_SEND_TIME;
    set_client_at(tfd, client);
    ev.events = EPOLLIN;
    ev.data.fd = tfd;
    if (epoll_ctl(epfd, EPOLL_CTL_ADD, tfd, &ev) != 0) {
        perror("epoll_ctl(ADD) on timerfd");
        set_client_at(tfd, NULL);
        close(tfd);
        client->timer_fd = -1;
        return;
    }
    debug_printf("client fd=%d: rtt=%ldus owd=%ldns clock_ts=%ld\n",
                 client->sock_fd, rtt_us, owd_ns, clock_ts);
}

/* try to complete reading the "SYNC\n" message on this client;
 * returns 0 if the client should be kept (either still waiting for more
 * data, or transitioned to ST_WAIT_SEND_TIME), -1 if it should be dropped
 * (protocol error, or peer closed / error on socket) */
static int handle_readable(client_t *client) {
    ssize_t n;
    for (;;) {
        n = read(client->sock_fd, client->rbuf + client->rbuf_len,
                 SYNC_MSG_LEN - client->rbuf_len);
        if (n < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                return 0;   /* nothing more to read for now */
            }
            if (errno == EINTR) {
                continue;
            }
            return -1;  /* socket error */
        }
        if (n == 0) {
            return -1;  /* peer closed the connection */
        }
        client->rbuf_len += n;
        if (client->rbuf_len == SYNC_MSG_LEN) {
            if (memcmp(client->rbuf, SYNC_MSG, SYNC_MSG_LEN) != 0) {
                return -1;  /* protocol error */
            }
            handle_sync_msg(client);
            return 0;
        }
        /* else, loop again, trying to read more (level-triggered epoll may
         * have more data available right away) */
    }
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
        set_nonblocking(fd);
        client = malloc_or_abort(sizeof(client_t));
        memset(client, 0, sizeof(client_t));
        client->sock_fd = fd;
        client->timer_fd = -1;
        client->state = ST_WAIT_SYNC_MSG;
        set_client_at(fd, client);
        ev.events = EPOLLIN;
        ev.data.fd = fd;
        if (epoll_ctl(epfd, EPOLL_CTL_ADD, fd, &ev) != 0) {
            perror("epoll_ctl(ADD)");
            set_client_at(fd, NULL);
            close(fd);
            free(client);
        }
    }
}

/* the timerfd of this client just fired: send the response and drop the
 * client */
static void handle_timer_fired(client_t *client) {
    uint64_t nb_expirations;
    char msg[32];
    int len, off = 0;

    /* we must read the timerfd to acknowledge the event, even though we
     * are about to close it anyway right after */
    (void)!read(client->timer_fd, &nb_expirations, sizeof(nb_expirations));

    len = snprintf(msg, sizeof(msg), "%ld\n", client->clock_ts);
    /* the message is tiny (a handful of bytes) and the socket send buffer
     * is virtually never full in this scenario, so a simple retry loop is
     * enough; we bound retries so that a stuck/broken client can never
     * cause us to loop indefinitely. */
    int retries_left = 1000;
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
    cleanup_client(client);
}

void _clock_syncd_main_loop(int listen_fd) {
    struct epoll_event ev, events[MAX_EPOLL_EVENTS];

    epfd = epoll_create1(0);
    if (epfd < 0) {
        perror("epoll_create1");
        exit(1);
    }
    set_nonblocking(listen_fd);
    ev.events = EPOLLIN;
    ev.data.fd = listen_fd;
    if (epoll_ctl(epfd, EPOLL_CTL_ADD, listen_fd, &ev) != 0) {
        perror("epoll_ctl(ADD) on listen socket");
        exit(1);
    }

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
                /* the timer fired: send the answer, regardless of
                 * EPOLLHUP/EPOLLERR (irrelevant for a timerfd) */
                handle_timer_fired(client);
                continue;
            }
            /* otherwise this event is about client->sock_fd */
            if (events[i].events & (EPOLLHUP | EPOLLERR)) {
                cleanup_client(client);
                continue;
            }
            if (client->state == ST_WAIT_SYNC_MSG) {
                if (handle_readable(client) != 0) {
                    cleanup_client(client);
                }
            } else {
                /* ST_WAIT_SEND_TIME: we do not expect more input, but if
                 * the peer closes early (or sends garbage), detect it and
                 * drop it, so we do not keep useless pending timers. */
                char discard[16];
                ssize_t r = read(fd, discard, sizeof(discard));
                if (r <= 0 && !(r < 0 && (errno == EAGAIN || errno == EWOULDBLOCK))) {
                    cleanup_client(client);
                }
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
