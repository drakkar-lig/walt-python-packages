#include <arpa/inet.h>
#include <assert.h>
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/tcp.h>
#include <regex.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <sys/timerfd.h>
#include <sys/timex.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#define DEBUG
#ifdef DEBUG
#define debug_printf(...) fprintf(stderr, __VA_ARGS__)
#else
#define debug_printf(...)   /* do nothing */
#endif

#define PERIOD_ADJTIME_SECS 15
#define MAX_EPOLL_EVENTS    32
#define MSG_MAX_LEN         256
#define NSEC_PER_SEC        1000000000L

/* In the adjtimex API, the unit of freqency offsets is ppm (parts
 * per million) with a 16-bit fractional part (see man adjtimex). */
static const double RATIO_TO_PPM = 1000000.0 * 65536.0;

enum CLOCK_STATE {
    CLOCK_OK,
    CLOCK_BAD,
    CLOCK_ALTERED,
    CLOCK_NO_ADJTIMEX,
};

/* This code implements the server side of the walt clock synchronization
 * protocol used by nodes at boot time (see walt-clock-sync on node side):
 *
 * For each client we proceed this way:
 * 1. The server waits for a second boundary and at this time it sends
 *    a message "SYNC <epoch-seconds>" to the client.
 *    Clients are only able to set their own clock with a 1-second
 *    resolution, hence the integer value.
 * 2. The client sets its clock using "busybox date -s" and then dumps
 *    the output of "busybox adjtimex" on the socket.
 * 3. The server saves the local date as t0 and parses the adjtimex dump.
 *    It saves timestamp remote_t0 using fields tv_sec and tv_usec.
 * 4. After PERIOD_ADJTIME_SECS, the server sends a message
 *    "DUMP_ADJTIMEX" to the client.
 * 5. The client dumps the output of "busybox adjtimex" on the socket.
 * 6. The server saves the local date as t1 and parses the adjtimex dump.
 *    It saves timestamp remote_t1 using fields tv_sec and tv_usec.
 *    Using t0, remote_t0, t1 and remote_t1 it computes a clock frequency
 *    offset and sends a message "ADJ_FREQ <freq-ppm>" to the client.
 *    Values t1 and remote_t1 are saved to t0 and remote_t0 for next
 *    adjustment step.
 * 7. The client adjusts its clock frequency using
 *    "busybox adjtimex -f <freq-ppm>"
 * 8. Loop to step 4.
 *
 * Timings are adjusted by considering the RTT estimate provided
 * by the kernel (getsockopt(TCP_INFO)).
 *
 * If the client has no busybox adjtimex applet, the process stops
 * after the first "SYNC" message.
 *
 * If we detect that some "busybox adjtimex" parameters on the client
 * were modified by another client process (such as an NTP or PTP
 * daemon) we also end the process. But if the WalT image booted on the
 * node does not provide such a synchronization protocol, the process
 * continues indefinitely.
 */

/* For performance, we store dates as 64-bit long integers, representing
 * a number of nanoseconds since the epoch.
 * We use the 30 left-most bits to store the number of nanoseconds and
 * higher order bits to store the number of seconds since the epoch. */
#define TS_NS_MASK ((1 << 30) -1)
#define debug_print_ts(var) debug_printf("%-10s = %ld.%09ld\n", #var, \
                           ts_seconds(var), ts_nanoseconds(var))
typedef long timestamp_t;

static inline timestamp_t ts_new(long secs, long nanosecs) {
    return (secs << 30) + nanosecs;
}

static inline long ts_seconds(timestamp_t ts) {
    return ts >> 30;
}

static inline long ts_nanoseconds(timestamp_t ts) {
    return ts & TS_NS_MASK;
}

static inline timestamp_t ts_add_s(timestamp_t ts, long secs) {
    return ts + (secs << 30);
}

static timestamp_t ts_add_ns(timestamp_t ts, long nanosecs) {
    long secs = ts >> 30;
    nanosecs += ts & TS_NS_MASK;
    while (nanosecs > NSEC_PER_SEC) {  /* unlikely */
        nanosecs -= NSEC_PER_SEC;
        secs += 1;
    }
    while (nanosecs < 0) {  /* unlikely too */
        nanosecs += NSEC_PER_SEC;
        secs -= 1;
    }
    return ts_new(secs, nanosecs);
}

static inline timestamp_t ts_sub_ns(timestamp_t ts, long nanosecs) {
    return ts_add_ns(ts, -nanosecs);
}

/* Returns t1-t2 as a total number of nanoseconds.
 * We use 'double' floating point return type to avoid
 * overflowing the size of 'long'. */
static double ts_diff_ns(timestamp_t t1, timestamp_t t2) {
    timestamp_t t;
    long t_s, t2_s;
    double ns;

    /* substract nanoseconds */
    t = ts_sub_ns(t1, ts_nanoseconds(t2));
    /* init result */
    ns = (double)ts_nanoseconds(t);
    /* substract seconds */
    t_s = ts_seconds(t);
    t2_s = ts_seconds(t2);
    if (t_s != t2_s) {
        ns += NSEC_PER_SEC * (double)(t_s - t2_s);
    }
    return ns;
}

static inline timestamp_t ts_now() {
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return ts_new(ts.tv_sec, ts.tv_nsec);
}

typedef enum {
    ST_WAIT_SEND_SYNC = 0,           /* wait before the initial SYNC */
    ST_WAIT_NEXT_ADJTIMEX = 1,       /* wait before next ADJTIMEX sync */
    ST_WAIT_RECV_DUMP_ADJTIMEX = 2,  /* wait before receiving ADJTIMEX dump */
} client_state_t;

typedef struct client {
    int sock_fd;
    int timer_fd;
    client_state_t state;
    union {
        /* SYNC phase */
        struct {
            /* SYNC integer value (unix ts, secs) */
            long sync_s;
        };
        /* ADJTIMEX phase */
        struct {
            /* date of last adjustment */
            timestamp_t t0;
            /* remote date at last adjustment */
            timestamp_t remote_t0;
            /* Frequency offset which should be applied to align
             * the clock frequency of this client to that of the server.
             * We use an exponentially weighted moving average of
             * successive estimates. */
            double ewma_base_freq_offset;
            /* current clock frequency adjustment offset */
            long freq_ppm;
            /* counter of adjtimex syncs */
            long adjtimex_counter;
        };
    };
} client_t;

/* fd -> client_t* table, indexed by fd value (fds are small integers).
 * Both a client's sock_fd and (once created) its timer_fd are recorded
 * here, pointing to the very same client_t. */
static client_t **clients = NULL;
static int clients_cap = 0;

static int epfd = -1;

static struct sigaction old_sigact_sigint, old_sigact_sigterm;
static enum {
    RUNNING,
    STOPPED
} status;

static void handle_signal(int sig) {
    /* restore initial signal handlers (the ones installed by python) */
    sigaction(SIGINT, &old_sigact_sigint, NULL);
    sigaction(SIGTERM, &old_sigact_sigterm, NULL);
    /* let python handle the signal */
    raise(sig);
    /* let our loop know it should stop, so that we can return
     * to python code. */
    status = STOPPED;
}

static void redirect_signals() {
    struct sigaction sigact;
    sigact.sa_handler = handle_signal;
    sigemptyset(&sigact.sa_mask);
    /* SA_NODEFER needed to re-raise signal in its own handler */
    sigact.sa_flags = SA_NODEFER;
    sigaction(SIGINT, &sigact, &old_sigact_sigint);
    sigaction(SIGTERM, &sigact, &old_sigact_sigterm);
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
    debug_printf("client fd=%d: cleanup\n", client->sock_fd);
    if (client->timer_fd >= 0) {
        cleanup_timer(client);
    }
    unregister_client_fd(client, client->sock_fd);
    close(client->sock_fd);
    free(client);
}

/* fetch selected tcp info fields of the socket */
static void get_tcp_info(int fd, long *rtt, long *lost, long *retrans) {
    struct tcp_info tcp_info;
    socklen_t optlen = sizeof(tcp_info);
    if (getsockopt(fd, IPPROTO_TCP, TCP_INFO, &tcp_info, &optlen) != 0) {
        perror("getsockopt");
        abort();
    }
    /* note: we use tcpi_min_rtt instead of tcpi_rtt for greater stability */
    *rtt = (long)tcp_info.tcpi_min_rtt;
    *lost = (long)tcp_info.tcpi_lost;
    *retrans = (long)tcp_info.tcpi_retrans;
    /*debug_printf("tcpi_min_rtt=%ldus tcpi_lost=%ld tcpi_retrans=%ld\n",
            *rtt, *lost, *retrans);*/
}

static long get_owd_ns(int fd) {
    long rtt_us, lost, retrans;
    get_tcp_info(fd, &rtt_us, &lost, &retrans);
    /* rtt (us) -> owd (ns) */
    return (rtt_us / 2) * 1000L;
}

static int create_timer() {
    int tfd = timerfd_create(CLOCK_REALTIME, 0);
    if (tfd < 0) {
        perror("timerfd_create");
        abort();
    }
    return tfd;
}

static void arm_timer_at(client_t *client, timestamp_t ts) {
    struct itimerspec its;

    memset(&its, 0, sizeof(its));
    its.it_value.tv_sec = ts_seconds(ts);
    its.it_value.tv_nsec = ts_nanoseconds(ts);
    /* it_interval left at 0: one-shot timer */
    if (timerfd_settime(
                client->timer_fd,
                TFD_TIMER_ABSTIME,
                &its,
                NULL) != 0) {
        perror("timerfd_settime");
        abort();
    }
}

static void send_message(client_t *client, char *fmt, ...) {
    int off = 0;
    int retries_left = 1000;
    va_list ap;
    char msg[MSG_MAX_LEN];
    int len;

    va_start(ap, fmt);
    len = vsnprintf(msg, MSG_MAX_LEN, fmt, ap);
    va_end(ap);
    if (len >= MSG_MAX_LEN) {
        fprintf(stderr,
                "Programming error: the message to be sent is too big.\n");
        abort();
    }

    /* the messages are small and the socket send buffer is virtually
     * never full in this scenario, so a simple retry loop is enough;
     * we bound retries so that a stuck/broken client can never
     * cause us to loop indefinitely. */
    while (off < len && retries_left > 0) {
        ssize_t n = write(client->sock_fd, msg + off, len - off);
        if (n > 0) {
            off += n;
            continue;
        }
        if (n < 0 && errno == EINTR) {
            continue;
        }
        break;  /* other error, give up sending to this client */
    }
}

static void plan_sync_msg(client_t *client) {
    long owd_ns, sync_s;
    timestamp_t now_ts, evt_ts;

    /* The node's tooling only supports setting the date
     * as an integer epoch number, so we wait for the next
     * second boundary. We take the one-way-delay into account:
     * we send the message slightly earlier so that the client
     * receives it at the right time. */
    owd_ns = get_owd_ns(client->sock_fd);
    now_ts = ts_now();
    sync_s = ts_seconds(now_ts) + 1;
    evt_ts = ts_new(sync_s, 0);
    evt_ts = ts_sub_ns(evt_ts, owd_ns);
    if (now_ts >= evt_ts) {
        /* too late for this second boundary, target the next one */
        sync_s += 1;
        evt_ts += ts_add_s(evt_ts, 1);
    }

    client->sync_s = sync_s;
    arm_timer_at(client, evt_ts);

    //debug_printf("client fd=%d: owd=%ldns sync_s=%ld\n",
    //             client->sock_fd, owd_ns, sync_s);
}

/* Here is how looks an adjtimex dump:

   # busybox adjtimex
       mode:         0
   -o  offset:       1140 us
   -f  freq.adjust:  -922508 (65536 = 1ppm)
       maxerror:     214152
       esterror:     57
       status:       8193 (PLL)
   -p  timeconstant: 6
       precision:    1 us
       tolerance:    32768000
   -t  tick:         10000 us
       time.tv_sec:  1787814126
       time.tv_usec: 466362536
       return value: 0 (clock synchronized)

   With older versions of busybox, "freq.adjust"
   was labelled "frequency".
*/
static const char *const RE_BB_ADJTIMEX =
"("
    "("
        "offset" "|"
        "freq[.]adjust" "|"
        "frequency" "|"
        "status" "|"
        "tolerance" "|"
        "time.tv_u?sec"
    ")" ":" "[^\n]*" "\n"
")" "|"
"("
    "\n\n" "|"
    "NO_BB_ADJTIMEX\n"
")";
#define NUM_FIELDS  6
static regex_t REGEX_BB_ADJTIMEX;

/* encode chars as smaller integers for use in associative
 * arrays below. */
#define ORD(c) ((c)-'a')

static enum CLOCK_STATE analyse_bb_adjtimex_output(
        client_t *client,
        timestamp_t *out_ts,
        long *out_tolerance_ppm) {
    long offset = 0,
         freq_ppm = 0,
         status = 0,
         tv_sec = 0,
         tv_usec = 0,
         tolerance_ppm = 0;
    regmatch_t match;
    size_t buflen = 1024;
    ssize_t n;
    char buf[buflen], *end_buf, *cur, *end_read, *match_end, distinctive_c;
    /* 1st-char -> index of distinctive char */
    int distinctive_index[] = {
        /* "offset" -> 'o' */
        [ORD('o')] = 0,
        /* "freq.adjust" or "frequency" -> 'f' */
        [ORD('f')] = 0,
        /* "status" -> 'a' */
        [ORD('s')] = 2,
        /* "time.tv_sec" -> 's'
           "time.tv_usec" -> 'u',
           "tolerance" -> 'e' */
        [ORD('t')] = 8,
    };
    /* distinctive char -> storage variable */
    long* vars[] = {
        [ORD('o')] = &offset,
        [ORD('f')] = &freq_ppm,
        [ORD('a')] = &status,
        [ORD('s')] = &tv_sec,
        [ORD('u')] = &tv_usec,
        [ORD('e')] = &tolerance_ppm,
    };
    int num_fields_found = 0;

    end_buf = buf + buflen;
    end_read = buf;
    cur = buf;
    while (1) {
        n = read(client->sock_fd, end_read, end_buf - end_read);
        if (n <= 0) {
            return CLOCK_BAD;
        }
        end_read += n;

        if (end_read == end_buf) {
            /* we read 1024 chars, we can't append '\0' and
             * this message is bigger than expected anyway. */
            return CLOCK_BAD;
        }

        *end_read = '\0';
        while (1) {
            if (regexec(&REGEX_BB_ADJTIMEX,
                        cur, 1, &match, 0) == REG_NOMATCH) {
                /* we need to read more, so leave the inner loop
                 * and let the outer one continue. */
                break;
            }

            match_end = cur + match.rm_eo;
            cur += match.rm_so;

            if ((*cur) == '\n') {
                /* we reached the ending tag "\n\n"
                 * before finding all information */
                fprintf(stderr, "Could not parse adjtime "
                                "data successfully!\n");
                printf("%s", buf);
                return CLOCK_BAD;
            }

            if ((*cur) == 'N') {
                /* the client sent us NO_BB_ADJTIMEX */
                fprintf(stderr, "client fd=%d: no busybox adjtimex applet.\n",
                        client->sock_fd);
                return CLOCK_NO_ADJTIMEX;
            }

            /* otherwise the regex found one of the fields */
            num_fields_found += 1;
            distinctive_c = cur[distinctive_index[ORD(*cur)]];

            /* point after the colon */
            cur = strchr(cur, ':')+1;

            /* skip whitespace */
            while (isspace(*cur)) cur++;

            /* read and save value */
            *(vars[ORD(distinctive_c)]) = strtol(cur, NULL, 10);

            /* check if we got all information */
            if (num_fields_found == NUM_FIELDS) {
                /* yes, we have read all needed fields */

                if (offset != 0) {
                    debug_printf("client fd=%d: "
                                 "something else changed offset value\n",
                                 client->sock_fd);
                    /* something changed the offset value */
                    return CLOCK_ALTERED;
                }

                if (freq_ppm != client->freq_ppm) {
                    debug_printf("client fd=%d: "
                                 "something else changed freq_ppm\n",
                                 client->sock_fd);
                    /* something changed the frequency offset after us */
                    return CLOCK_ALTERED;
                }

                if ((status & STA_UNSYNC) == 0) {
                    debug_printf("client fd=%d: "
                                 "something else removed the UNSYNC flag\n",
                                 client->sock_fd);
                    /* something started taking care of clock sync */
                    return CLOCK_ALTERED;
                }

                /* all is fine, fill in 'out_ts' and 'out_tolerance_ppm' */
                if ((status & STA_NANO) > 0) {
                    /* tv_usec actually encodes nanoseconds */
                    *out_ts = ts_new(tv_sec, tv_usec);
                }
                else {
                    /* tv_usec encodes microseconds */
                    *out_ts = ts_new(tv_sec, tv_usec * 1000L);
                }
                *out_tolerance_ppm = tolerance_ppm;

                /* return successfully */
                return CLOCK_OK;
            }

            /* point 'cur' to the '\n' ending the line (pointing
             * after it could make us miss the '\n\n' pattern) */
            cur = match_end-1;
        }
    }
}

/* Our algorithm is based on three clock values observed
 * on the remote node and here at the server:
 * - t0 / remote_t0: clock values at previous step
 * - t1 / remote_t1: clock values observed just now
 * - t2: clock value planned for next step
 *
 * The client ran from t0 to t1 with its frequency adjusted at freq0.
 * We want to ajust its frequency to freq1 so that its clock is
 * perfectly synchronized with the local clock (ideally) at t2 (next step).
 *
 * In order to compare tx and remote_tx values, remote_tx values
 * are adjusted by adding the one-way-delay.
 *
 * Our estimation of the base frequency adjustment this client
 * needs to match the clock frequency of the server, considering
 * the offset observed at t1, is:
 * base_freq = current_freq * (t1-t0) / (remote_t1-remote_t0)
 *
 * We want to adjust the frequency to have the clock offset
 * observed at t1 compensated at t2, so:
 * adjusted_freq = base_freq * (t2-remote_t1) / (t2-t1)
 *
 * For instance, if the remote clock is 1ms late at t1,
 * (i.e., remote_t1 = t1 - 1ms), then the remote clock should
 * be made a little faster than the base frequency, so that
 * the remote clock is able to increment 1ms more when we check
 * at t2.
 *
 * The adjtimex API needs the frequency expressed as `1.0 + freq_offset`,
 * and we can rewrite formulas to exclude this 1.0 constant and improve
 * numerical stability:
 * 1.0 + base_offset = (1.0 + current_offset) *
 *                      (t1-t0) / (remote_t1-remote_t0)
 *                    = (1.0 + current_offset) *
 *                      (1.0 + ((t1-t0) - (remote_t1-remote_t0)) /
 *                             (remote_t1-remote_t0))
 *                    = (1.0 + current_offset) *
 *                      (1.0 + epsilon1)
 *
 * with epsilon1 = ((t1-remote_t1) - (t0-remote_t0)) /
 *                 (remote_t1-remote_t0)
 *
 * So:
 * base_offset = current_offset * (1.0 + epsilon1) + epsilon1
 *
 * We can also apply similar transformations to compute the
 * adjusted frequency offset:
 * 1.0 + adjusted_offset = (1.0 + base_offset) *
 *                         (t2-remote_t1) / (t2-t1)
 * 1.0 + adjusted_offset = (1.0 + base_offset) *
 *                         (1.0 + ((t2-remote_t1) - (t2-t1)) /
 *                                (t2-t1))
 * 1.0 + adjusted_offset = (1.0 + base_offset) *
 *                         (1.0 + (t1-remote_t1) / (t2-t1))
 * 1.0 + adjusted_offset = (1.0 + base_offset) *
 *                         (1.0 + epsilon2)
 *
 * with epsilon2 = (t1-remote_t1) / (t2-t1)
 *
 * So:
 * adjusted_offset = base_offset * (1.0 + epsilon2) + epsilon2
 *
 * For better stability, we apply an exponentially weighted moving
 * average on "base_offset", and, after a few initial steps, on
 * "adjusted_offset" too.
 */

static inline double get_estimated_base_freq_offset(
        double freq_offset,
        timestamp_t t0, timestamp_t remote_t0,
        timestamp_t t1, timestamp_t remote_t1) {
    double epsilon1 = (
            ts_diff_ns(t1, remote_t1) - ts_diff_ns(t0, remote_t0)
        ) / ts_diff_ns(remote_t1, remote_t0);
    return freq_offset * (1.0 + epsilon1) + epsilon1;
}

static inline double get_adjusted_freq_offset(
        double base_offset,
        timestamp_t t1, timestamp_t remote_t1,
        timestamp_t t2) {
    double epsilon2 = (ts_diff_ns(t1, remote_t1)) / ts_diff_ns(t2, t1);
    return base_offset * (1.0 + epsilon2) + epsilon2;
}

static int handle_adjtime_response(client_t *client) {
    int res;
    timestamp_t t0, remote_t0, t1, remote_t1, t2, t2_req;
    long owd_ns, tolerance_ppm, freq_ppm;
    double freq_offset, estimated_base_offset, ewma_weight,
           adjusted_freq_offset;

    /* record receival time asap */
    t1 = ts_now();

    /* read the one-way-delay measured on the socket */
    owd_ns = get_owd_ns(client->sock_fd);

    /* plan time for next step (t2) */
    t2 = ts_add_s(t1, PERIOD_ADJTIME_SECS);

    /* read and analyse the busybox adjtimex dump the node sent */
    res = analyse_bb_adjtimex_output(client, &remote_t1, &tolerance_ppm);
    switch (res) {
        case CLOCK_OK:
            //debug_printf("received adjtimex data\n");
            break;
        case CLOCK_BAD:
            send_message(client,
                         "QUIT wrong adjtimex dump\n");
            return -1;
        case CLOCK_ALTERED:
            send_message(client,
                         "QUIT another process started adjustments\n");
            return -1;
        case CLOCK_NO_ADJTIMEX:
            send_message(client,
                         "QUIT no busybox adjtimex applet\n");
            return -1;
    }

    /* - t1 is taken when the server receives the message
     * - remote_t1 was written inside this message, but then this
     *   remote clock value was recorded before the message crossed
     *   the network.
     * In order to properly compare the values, we add the one-way-delay
     * value to remote_t1. */
    remote_t1 = ts_add_ns(remote_t1, owd_ns);

    debug_printf("client fd=%d: step %ld -- estimated offset: %ldus\n",
                 client->sock_fd,
                 client->adjtimex_counter,
                 (long)(ts_diff_ns(remote_t1, t1)/1000.0));
    /* unless it is the first ADJTIMEX synchronization (in which case
     * t0 & remote_t0 are not available yet), analyse node drift and
     * offset and send a request to adjust its clock frequency. */
    if (client->adjtimex_counter > 0) {
        t0 = client->t0;
        remote_t0 = client->remote_t0;
        freq_offset = client->freq_ppm / RATIO_TO_PPM;
        /*
        debug_print_ts(t0);
        debug_print_ts(remote_t0);
        debug_print_ts(t1);
        debug_print_ts(remote_t1);
        debug_print_ts(t2);
        */
        /* estimate the base freq offset (the freq offset to align
         * the remote clock to the local one) according to measurements
         * at t0 and t1 */
        estimated_base_offset = get_estimated_base_freq_offset(
                freq_offset, t0, remote_t0, t1, remote_t1);
        /* compute the exponentially weighted moving average */
        if (client->adjtimex_counter > 1) {
            if (client->adjtimex_counter >= 10) {
                ewma_weight = 0.1;
            }
            else {
                ewma_weight = 1.0 / client->adjtimex_counter;
            }
            client->ewma_base_freq_offset =
                client->ewma_base_freq_offset * (1.0 - ewma_weight) +
                estimated_base_offset * ewma_weight;
        }
        else {
            client->ewma_base_freq_offset = estimated_base_offset;
        }
        /* compute the adjusted freq offset to have the current
         * time offset compensated at t2 */
        adjusted_freq_offset = get_adjusted_freq_offset(
                client->ewma_base_freq_offset, t1, remote_t1, t2);
        freq_ppm = (long)(adjusted_freq_offset * RATIO_TO_PPM);
        /* start applying an exponentially weighted moving average
         * in the stable phase */
        if (client->adjtimex_counter >= 12) {
            if (client->adjtimex_counter >= 20) {
                ewma_weight = 0.1;
            }
            else {
                ewma_weight = 1.0 / (client->adjtimex_counter-10);
            }
            client->freq_ppm = client->freq_ppm * (1.0 - ewma_weight) +
                freq_ppm * ewma_weight;
        }
        else {
            client->freq_ppm = freq_ppm;
        }
        /* ensure we don't exceed tolerance_ppm */
        if (client->freq_ppm > tolerance_ppm) {
            client->freq_ppm = tolerance_ppm;
        }
        if (client->freq_ppm < -tolerance_ppm) {
            client->freq_ppm = -tolerance_ppm;
        }
        /* request the node to adjust its clock frequency */
        send_message(client, "ADJ_FREQ %ld\n", client->freq_ppm);
        printf("client fd=%d: Freq base %.3e ppm adjust %ld\n",
                client->sock_fd,
                client->ewma_base_freq_offset, client->freq_ppm);
    }
    client->adjtimex_counter += 1;

    /* plan next synchronization.
     * Note: we will send message DUMP_ADJTIMEX to the node and it will
     * then dump the required data in return, so the response will be
     * delayed by a full RTT delay. */
    t2_req = ts_sub_ns(t2, owd_ns<<1);
    arm_timer_at(client, t2_req);
    client->state = ST_WAIT_NEXT_ADJTIMEX;
    client->t0 = t1;
    client->remote_t0 = remote_t1;
    return 0;
}

/* accept and initialize a new client */
static void accept_client(int listen_fd) {
    client_t *client;
    int fd = accept(listen_fd, NULL, NULL);
    if (fd < 0) {
        /* EINTR or unexpected error, ignore and keep serving
         * other clients */
        return;
    }
    client = malloc_or_abort(sizeof(client_t));
    memset(client, 0, sizeof(client_t));
    client->sock_fd = fd;
    register_client_fd(client, client->sock_fd);
    client->timer_fd = create_timer();
    register_client_fd(client, client->timer_fd);
    client->state = ST_WAIT_SEND_SYNC;
    plan_sync_msg(client);
    client->freq_ppm = 0.;
}

int discard_client_input(client_t *client) {
    size_t buflen = 1024;
    char buf[buflen];
    int n;
    n = read(client->sock_fd, buf, buflen);
    if (n <= 0) {
        return -1;
    }
    return 0;
}

void _clock_syncd_main_loop(int listen_fd) {
    struct epoll_event events[MAX_EPOLL_EVENTS];

    epfd = epoll_create1(0);
    if (epfd < 0) {
        perror("epoll_create1");
        exit(1);
    }
    register_fd(listen_fd);

    if (regcomp(&REGEX_BB_ADJTIMEX, RE_BB_ADJTIMEX, REG_EXTENDED)) {
        perror("regcomp");
        exit(1);
    }

    redirect_signals();

    status = RUNNING;
    while (status == RUNNING) {
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
                accept_client(listen_fd);
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
                        //debug_printf("timer event -- send SYNC\n");
                        /* send the SYNC message */
                        send_message(client, "SYNC %ld\n", client->sync_s);
                        /* wait for the 1st ADJTIMEX dump the node will
                         * send in return */
                        client->state = ST_WAIT_RECV_DUMP_ADJTIMEX;
                        break;
                    case ST_WAIT_NEXT_ADJTIMEX:
                        //debug_printf("timer event -- send DUMP_ADJTIMEX\n");
                        /* send ADJTIME info request */
                        send_message(client, "DUMP_ADJTIMEX\n");
                        client->state = ST_WAIT_RECV_DUMP_ADJTIMEX;
                        break;
                    default:
                        fprintf(stderr, "Case not implemented! Giving up.\n");
                        abort();
                }
                continue;
            }
            /* otherwise this event is about client->sock_fd */
            if (events[i].events & (EPOLLHUP | EPOLLERR)) {
                cleanup_client(client);
                continue;
            }
            if (client->state == ST_WAIT_RECV_DUMP_ADJTIMEX) {
                if (handle_adjtime_response(client) != 0) {
                    cleanup_client(client);
                }
            }
            else {
                /* The node runs "busybox adjtimex; echo" to implement
                 * the ending "\n\n" pattern, and this most likely
                 * results in two TCP segments. Reading up to the ending
                 * pattern would block the server a few milliseconds
                 * waiting for the 2nd TCP segment.
                 * That's why handle_adjtime_response() purposedly stops
                 * reading as soon as it has read all required fields.
                 * But has a side effect, we may still have unread data
                 * and get here. We just discard this unused data. */
                if (discard_client_input(client) != 0) {
                    /* empty read */
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
            send_message(client,
                         "QUIT walt-server-syncd stopping\n");
            cleanup_client(client);
        }
    }
    free(clients);
    clients = NULL;
    clients_cap = 0;
    close(epfd);
    regfree(&REGEX_BB_ADJTIMEX);
    epfd = -1;
}
