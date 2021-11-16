#define _GNU_SOURCE
#include <sys/select.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/uio.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
#include <time.h>
#include <signal.h>
#include <errno.h>
#include <stdlib.h>
#include <assert.h>
#include <string.h>
#include <stdint.h>

#define MIN(i, j) (((i) > (j))?(j):(i))
#define MAX(i, j) (((i) > (j))?(i):(j))

//#define DEBUG
#ifdef DEBUG
#define debug_printf printf
#else
#define debug_printf(...)   /* do nothing */
#endif

static struct sigaction old_sigact;
static enum {
    RUNNING,
    STOPPED_SHOULD_REINIT,
    STOPPED_SHOULD_ABORT
} status;

void handle_signal(int sig) {
    /* restore initial signaling */
    sigaction(SIGINT, &old_sigact, NULL);
    /* let python handle the signal */
    raise(sig);
    status = STOPPED_SHOULD_ABORT;
}

void redirect_sigint() {
    struct sigaction sigact;
    /* we may be interrupted by SIGINT */
    sigact.sa_handler = handle_signal;
    sigemptyset(&sigact.sa_mask);
    sigact.sa_flags = SA_NODEFER;  /* needed to re-raise signal in its own handler */
    sigaction(SIGINT, &sigact, &old_sigact);
}

/* note: ternary op in this macro is just here to avoid warn unused result */
#define write_stderr(msg) (void)(write(2, msg, strlen(msg))?1:0)

static inline int write_fd(int fd, unsigned char *start, unsigned char *end,
                            char *fd_label) {
    ssize_t sres;
    while (start < end) {
        sres = write(fd, start, end - start);
        debug_printf("write fd=%d result=%ld\n", fd, sres);
        if (fd_label) {
            if (sres == 0) {
                write_stderr("short write on ");
                write_stderr(fd_label);
                write_stderr("\n");
            }
            if (sres == -1) {
                write_stderr(fd_label);
                write_stderr(" write error\n");
                return -1;
            }
        }
        start += sres;
    }
    return 0;
}

/* packet length is encoded as 2 bytes, big endian */
#define PARSE_LEN_BIG_ENDIAN(i1, i0) (((i1)<<8) + (i0))
static inline ssize_t compute_packet_len(unsigned char *len_pos) {
    return PARSE_LEN_BIG_ENDIAN(*len_pos, *(len_pos+1));
}

static inline void store_packet_len(unsigned char *len_pos, ssize_t sres) {
    len_pos[0] = (unsigned char)(sres >> 8);
    len_pos[1] = (unsigned char)(sres & 0xff);
}

/* we have to handle partial reads / writes when using readv() or writev().
 * for this we define full_readv() and full_writev() below, and both
 * of these functions call full_iov_work() for the internal machinery. */
typedef ssize_t (*iov_func_t)(int fd, const struct iovec *iov, int iovcnt);

static inline int full_iov_work(iov_func_t f, int fd, struct iovec *iov, int iovcnt, ssize_t size) {
    ssize_t result_size;
    int res;
    result_size = f(fd, iov, iovcnt);
    if (result_size == -1) {
        return -1;
    }
    if (result_size == size) {
        return 0; // ok done
    }
    size -= result_size;
    // got a partial readv/writev, check where it stopped
    // first, pass full segments
    while (result_size >= (ssize_t)iov[0].iov_len) {
        result_size -= iov[0].iov_len;
        iov += 1;
        iovcnt -= 1;
    }
    // if needed, update last partially read/written segment
    if (result_size > 0) {
        iov[0].iov_base += result_size;
        iov[0].iov_len -= result_size;
    }
    // recurse
    res = full_iov_work(f, fd, iov, iovcnt, size);
    // restore partially read/written segment if changed
    if (result_size > 0) {
        iov[0].iov_base -= result_size;
        iov[0].iov_len += result_size;
    }
    return res;
}

int full_readv(int fd, struct iovec *iov, int iovcnt, ssize_t size) {
    int res = full_iov_work(readv, fd, iov, iovcnt, size);
    if (res == -1) {
        perror("readv()");
        return -1;
    }
    return 0;
}

int full_writev(int fd, struct iovec *iov, int iovcnt, ssize_t size) {
    int res = full_iov_work(writev, fd, iov, iovcnt, size);
    if (res == -1) {
        perror("writev()");
        return -1;
    }
    return 0;
}

#define UDP_PAYLOAD_MAX_SIZE                4096    /* ensured by interface MTU, see comment in const.py */
#define PACKET_BATCH_BITS                   5
#define PACKET_BATCH_SIZE                   (1<<PACKET_BATCH_BITS)
/* caution: if changing LENGTH_SIZE, change two following macros too */
#define LENGTH_SIZE                         2       /* size to encode packet length */
/* since LENGTH_SIZE is 2, level on lengths buffer is on a length boundary
 * if it is an even number */
#define ON_LENGTH_BOUNDARY(level)           (((level) & 0x1) == 0)
#define BUF_LEN_LEVEL_TO_NUM_MSGS(level)    ((level) >> 1)  /* divide by 2 */
#define BUFFER_LENGTHS_SIZE                 (LENGTH_SIZE << PACKET_BATCH_BITS)

struct io_buffers {
    unsigned char buf_len[BUFFER_LENGTHS_SIZE];
    struct mmsghdr recv_msgs[PACKET_BATCH_SIZE];
    struct mmsghdr send_msgs[PACKET_BATCH_SIZE];
    struct iovec recv_iovecs[PACKET_BATCH_SIZE];
    struct iovec send_iovecs[PACKET_BATCH_SIZE];
};

void init_io_buffers(struct io_buffers *iobuf) {
    int i;
    memset(iobuf->recv_msgs, 0, sizeof(iobuf->recv_msgs));
    memset(iobuf->send_msgs, 0, sizeof(iobuf->send_msgs));
    for (i = 0; i < PACKET_BATCH_SIZE; i++) {
        /* note: we reuse the same packet buffers for sending and receiving,
         * but we prepare two pairs of struct iovec & struct mmsghdr vectors
         * for indexing them quickly. */
        iobuf->recv_iovecs[i].iov_base         = malloc(sizeof(unsigned char) * UDP_PAYLOAD_MAX_SIZE);
        iobuf->recv_iovecs[i].iov_len          = UDP_PAYLOAD_MAX_SIZE;
        iobuf->recv_msgs[i].msg_hdr.msg_iov    = &iobuf->recv_iovecs[i];
        iobuf->recv_msgs[i].msg_hdr.msg_iovlen = 1;
        iobuf->send_iovecs[i].iov_base                = iobuf->recv_iovecs[i].iov_base; /* shared with recv */
        /* send_iovecs[i].iov_len will be adjusted when needed */
        iobuf->send_msgs[i].msg_hdr.msg_iov    = &iobuf->send_iovecs[i];
        iobuf->send_msgs[i].msg_hdr.msg_iovlen = 1;
    }
}

void free_io_buffers(struct io_buffers *iobuf) {
    int i;
    for (i = 0; i < PACKET_BATCH_SIZE; ++i) {
        free(iobuf->recv_iovecs[i].iov_base);
    }
}

int sock_to_streams(struct io_buffers *iobuf,
                    int sock_fd, int lengths_fd, int packets_fd) {
    unsigned char *plen;
    int num_msgs, res, i;
    ssize_t packet_len, total_size;

    /* read multiple UDP packets */
    num_msgs = recvmmsg(sock_fd, iobuf->recv_msgs, PACKET_BATCH_SIZE, MSG_DONTWAIT, NULL);
    if (num_msgs == -1) {
        perror("recvmmsg()");
        status = STOPPED_SHOULD_REINIT;
        return -1;
    }
    /* prepare next writes */
    total_size = 0;
    for (i = 0, plen = iobuf->buf_len; i < num_msgs; ++i, plen += LENGTH_SIZE) {
        packet_len = iobuf->recv_msgs[i].msg_len;
        debug_printf("l2tp -> ssh %d bytes\n", (int)packet_len);
        store_packet_len(plen, packet_len);
        iobuf->send_iovecs[i].iov_len = packet_len;
        total_size += packet_len;
    }
    /* write packets length */
    res = write_fd(lengths_fd, iobuf->buf_len, plen, "ssh lengths channel");
    if (res == -1) {
        status = STOPPED_SHOULD_REINIT;
        return -1;
    }
    /* write packets content */
    res = full_writev(packets_fd, iobuf->send_iovecs, num_msgs, total_size);
    if (res == -1) {
        status = STOPPED_SHOULD_REINIT;
        return -1;
    }
    return 0;
}

static inline uint32_t l2tp_parse_session_id(unsigned char *l2tp_packet) {
    /* session ID is defined as a 32-bit unsigned integer on bytes 4 to 7 of L2TP header */
    return ntohl(*((uint32_t*)(l2tp_packet+4)));
}

int streams_to_sock(struct io_buffers *iobuf,
                    int lengths_fd, int packets_fd, int sock_fd) {
    unsigned char *plen;
    int num_msgs, res, i;
    ssize_t packet_len, total_size, read_size, buf_len_level;

    /* read lengths buffer */
    buf_len_level = 0;
    while (1) {
        read_size = read(lengths_fd, iobuf->buf_len + buf_len_level,
                         BUFFER_LENGTHS_SIZE - buf_len_level);
        if (read_size > 0) {
            buf_len_level += read_size;
            if (!ON_LENGTH_BOUNDARY(buf_len_level)) {
                continue;   // highly unusual...
            }
            break;  // ok
        }
        if (read_size == -1) {
            perror("read() on lengths ssh channel");
        }
        else {  // read_size is 0
            fprintf(stderr, "empty read on lengths ssh channel\n");
        }
        status = STOPPED_SHOULD_REINIT;
        return -1;
    }
    num_msgs = BUF_LEN_LEVEL_TO_NUM_MSGS(buf_len_level);

    /* prepare full_readv() */
    total_size = 0;
    for (i = 0, plen = iobuf->buf_len; i < num_msgs; ++i, plen += LENGTH_SIZE) {
        packet_len = compute_packet_len(plen);
        debug_printf("ssh -> l2tp %d bytes\n", (int)packet_len);
        /* add to send_iovecs for this UDP packet */
        iobuf->send_iovecs[i].iov_len = packet_len;
        total_size += packet_len;
    }

    /* read packets from packets_stdout */
    res = full_readv(packets_fd, iobuf->send_iovecs, num_msgs, total_size);
    debug_printf("full_readv num_msgs=%d total_size=%d result=%d\n",
                   num_msgs, (int)total_size, res);
    if (res == -1) {
        status = STOPPED_SHOULD_REINIT;
        return -1;
    }

    /* send packets to L2TP socket */
    res = sendmmsg(sock_fd, iobuf->send_msgs, num_msgs, 0);
    debug_printf("sendmmsg num_msgs=%d result=%d\n", num_msgs, res);
    if (res == -1) {
        perror("sendmmsg()");
        status = STOPPED_SHOULD_REINIT;
        return -1;
    }
    return 0;
}

int client_transmission_loop(int lengths_stdin, int lengths_stdout,
                             int packets_stdin, int packets_stdout, int sock_fd) {
    int res, max_fd;
    fd_set fds, init_fds;
    struct io_buffers io_buffers;

    redirect_sigint();

    init_io_buffers(&io_buffers);

    FD_ZERO(&init_fds);
    FD_SET(lengths_stdout, &init_fds);
    FD_SET(sock_fd, &init_fds);
    max_fd = MAX(lengths_stdout, sock_fd) + 1;

    /* start select loop
       we will:
       * transfer packets coming from the tap interface to packets_stdin & lengths_stdin
       * transfer packets coming from packets_stdout & lengths_stdout to the tap interface
    */
    status = RUNNING;
    while (status == RUNNING) {
        fds = init_fds;
        res = select(max_fd, &fds, NULL, NULL, NULL);
        if (res < 1) {
            perror("select error");
            status = STOPPED_SHOULD_REINIT;  // caller should reinit
            break;
        }
        if (FD_ISSET(sock_fd, &fds)) {
            sock_to_streams(&io_buffers, sock_fd, lengths_stdin, packets_stdin);
        }
        else { // lengths_stdout fd is set
            streams_to_sock(&io_buffers, lengths_stdout, packets_stdout, sock_fd);
        }
    }

    free_io_buffers(&io_buffers);

    assert(status != RUNNING);
    return (status == STOPPED_SHOULD_REINIT);
}

#define SERVER_SOCK_FD  3
#define L2TP_SOCK_FD    4
#define PACKET_BUFFER_SIZE  (LENGTH_SIZE + UDP_PAYLOAD_MAX_SIZE)
#define LENGTHS_READ_FD_TO_SESSION_ID(fd)            ((fd)-0)
#define SESSION_ID_TO_LENGTHS_READ_FD(session_id)    ((session_id)+0)
#define SESSION_ID_TO_LENGTHS_WRITE_FD(session_id)   ((session_id)+1)
#define SESSION_ID_TO_PACKETS_READ_FD(session_id)    ((session_id)+3)
#define SESSION_ID_TO_PACKETS_WRITE_FD(session_id)   ((session_id)+4)

struct server_context {
    fd_set fds;
    fd_set init_fds;
    int init_max_fd;
    struct io_buffers io_buffers;
    int(*on_disconnect)(int session_id);
};

int client_disconnection_handler(struct server_context *ctx, int session_id) {
    int ep_lengths_stdin_fd = SESSION_ID_TO_LENGTHS_READ_FD(session_id);
    printf("disconnecting client session_id=%d error=%s\n", session_id, strerror(errno));
    FD_CLR(ep_lengths_stdin_fd, &ctx->init_fds); /* for next fd loop */
    FD_CLR(ep_lengths_stdin_fd, &ctx->fds); /* for current fd loop */
    ctx->init_max_fd = ctx->on_disconnect(session_id);
    if (ctx->init_max_fd == -1) {
        status = STOPPED_SHOULD_ABORT;
        return -1;
    }
    return 0;
}

static inline int client_still_ok(struct server_context *ctx, int session_id) {
    /* does the select() still listens for incoming data on this client connection?
     * if not, this means we previously disconnected this client. */
    return FD_ISSET(SESSION_ID_TO_LENGTHS_READ_FD(session_id), &ctx->init_fds);
}

/* The following function is a variant of sock_to_streams() above function
 * but used at the server.
 * When receiving traffic on the L2TP socket, packets may target different
 * clients. Thus the server has to read the session id from L2TP header
 * in order to know on which ssh channels length and packet content should
 * be sent.
 * For efficiency, all messages available from the L2TP socket buffer are
 * read at once. Then, these messages are processed per batch of consecutive
 * messages having the same session id, thus targeting the same client. */
int sock_to_streams_l2tp_dispatch(struct server_context *ctx) {
    unsigned char *plen;
    int num_msgs, res, i, first_i, session_id, prev_session_id;
    ssize_t packet_len, total_size;
    struct io_buffers *iobuf = &ctx->io_buffers;

    /* read multiple UDP packets */
    num_msgs = recvmmsg(L2TP_SOCK_FD, iobuf->recv_msgs, PACKET_BATCH_SIZE, MSG_DONTWAIT, NULL);
    if (num_msgs == -1) {
        perror("recvmmsg()");
        status = STOPPED_SHOULD_REINIT;
        return -1;
    }

    /* process them per batch of consecutive messages targeting the same client */
    i = 0;
    while (i < num_msgs) {
        plen = iobuf->buf_len;
        prev_session_id = -1;
        first_i = i;
        total_size = 0;
        /* prepare next writes */
        for (; i < num_msgs; ++i, plen += LENGTH_SIZE) {
            /* read session id from L2TP header */
            session_id = (int)l2tp_parse_session_id(iobuf->send_iovecs[i].iov_base);
            if ((prev_session_id != -1) && (session_id != prev_session_id)) {
                session_id = prev_session_id;
                break;
            }
            debug_printf("found session_id=%d\n", session_id);
            packet_len = iobuf->recv_msgs[i].msg_len;
            debug_printf("l2tp -> ssh %d bytes\n", (int)packet_len);
            store_packet_len(plen, packet_len);
            iobuf->send_iovecs[i].iov_len = packet_len;
            total_size += packet_len;
        }
        /* we may have disconnected this client, earlier in the processing of this message batch,
         * by calling client_disconnection_handler() below */
        if (!client_still_ok(ctx, session_id)) {
            debug_printf("client session_id=%d is down\n", session_id);
            continue;
        }
        /* write packets length */
        res = write_fd(SESSION_ID_TO_LENGTHS_WRITE_FD(session_id),
                       iobuf->buf_len, plen, "ssh lengths channel");
        if (res == 0) {
            /* write packets content */
            res = full_writev(SESSION_ID_TO_PACKETS_WRITE_FD(session_id),
                    &iobuf->send_iovecs[first_i], i - first_i, total_size);
        }
        if (res == -1) {
            client_disconnection_handler(ctx, session_id);
        }
    }
    return 0;
}

void server_transmission_loop(int(*on_connect)(), int(*on_disconnect)(int session_id)) {
    int res, max_fd, fd, session_id, ep_lengths_stdin_fd, ep_packets_stdin_fd;
    struct server_context ctx;

    redirect_sigint();

    init_io_buffers(&ctx.io_buffers);
    ctx.on_disconnect = on_disconnect;

    FD_ZERO(&ctx.init_fds);
    FD_SET(SERVER_SOCK_FD, &ctx.init_fds);
    FD_SET(L2TP_SOCK_FD, &ctx.init_fds);
    ctx.init_max_fd = L2TP_SOCK_FD;

    /* start select loop
     * python handles the smart part of the code and ensures that
     * each client is associated with a range of 8 consecutive file descriptors.
     * see comment on top of server.py */

    status = RUNNING;
    while (status == RUNNING) {
        ctx.fds = ctx.init_fds;
        max_fd = ctx.init_max_fd;
        debug_printf("select()");
        res = select(max_fd + 1, &ctx.fds, NULL, NULL, NULL);
        if (res < 1) {
            perror("select error");
            break;
        }
        for (fd = SERVER_SOCK_FD; fd <= max_fd; ++fd) {
            if (FD_ISSET(fd, &ctx.fds)) {
                if (fd == SERVER_SOCK_FD) {
                    session_id = on_connect();
                    if (session_id == -1) {
                        status = STOPPED_SHOULD_ABORT;
                        break;
                    }
                    if (session_id == 0) {
                        /* we got 1st client stream, we need the 2nd one,
                         * nothing to do for now */
                        continue;
                    }
                    ep_lengths_stdin_fd = SESSION_ID_TO_LENGTHS_READ_FD(session_id);
                    ep_packets_stdin_fd = SESSION_ID_TO_PACKETS_READ_FD(session_id);
                    printf("new client session_id=%d\n", session_id);
                    FD_SET(ep_lengths_stdin_fd, &ctx.init_fds);
                    if (ep_packets_stdin_fd > ctx.init_max_fd) {
                        ctx.init_max_fd = ep_packets_stdin_fd;
                    }
                }
                else {
                    debug_printf("event on fd=%d\n", fd);
                    res = 0;    // ok, up to now
                    if (fd == L2TP_SOCK_FD) { // packet on L2TP UDP socket
                        sock_to_streams_l2tp_dispatch(&ctx);
                    }
                    else { // not L2TP_SOCK_FD => ep_lengths_stdin_fd
                        ep_lengths_stdin_fd = fd;
                        session_id = LENGTHS_READ_FD_TO_SESSION_ID(fd);
                        ep_packets_stdin_fd = SESSION_ID_TO_PACKETS_READ_FD(session_id);
                        res = streams_to_sock(&ctx.io_buffers, ep_lengths_stdin_fd,
                                              ep_packets_stdin_fd, L2TP_SOCK_FD);
                        if (res == -1) {
                            // client issue, disconnect
                            client_disconnection_handler(&ctx, session_id);
                        }
                    }
                }
                if (status == STOPPED_SHOULD_ABORT) {
                    break;
                }
            }
        }
    }
    free_io_buffers(&ctx.io_buffers);
}
