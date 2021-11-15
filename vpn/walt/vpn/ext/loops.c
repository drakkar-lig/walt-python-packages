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

static inline int read_fd_once(int fd, unsigned char *start, ssize_t max_size,
                                 ssize_t *out_length, char *fd_label) {
    ssize_t sres;
    debug_printf("read fd=%d max_size=%ld\n", fd, max_size);
    sres = read(fd, start, max_size);
    if (sres < 1) {
        if (fd_label) {
            if (sres == 0) {
                write_stderr("short read on ");
                write_stderr(fd_label);
                write_stderr("\n");
            }
            else {
                write_stderr(fd_label);
                write_stderr(" read error\n");
            }
        }
        return -1;
    }
    start += sres;
    if (out_length != NULL) {
        *out_length = sres;
    }
    return 0;
}

static inline int read_fd(int fd, unsigned char *start, ssize_t size,
                          char *fd_label) {
    ssize_t sres;
    int res;
    while (size > 0) {
        res = read_fd_once(fd, start, size, &sres, fd_label);
        if (res == -1) {
            return res;
        }
        start += sres;
        size -= sres;
    }
    return 0;
}

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

typedef struct {
    int size;
    int level;
    unsigned char *buf;
    unsigned char *buf_end;
    unsigned char *fill_pos;
    unsigned char *flush_pos;
} circular_buffer_t;

int cbuf_setup(circular_buffer_t *cbuf, int size) {
    cbuf->size = size;
    cbuf->level = 0;
    cbuf->buf = malloc(sizeof(unsigned char) * size);
    if (cbuf->buf == NULL) {
        return -1;
    }
    cbuf->buf_end = cbuf->buf + size;
    cbuf->fill_pos = cbuf->buf;
    cbuf->flush_pos = cbuf->buf;
    return 0;
}

void cbuf_release(circular_buffer_t *cbuf) {
    free(cbuf->buf);
}

int cbuf_fill(circular_buffer_t *cbuf, int fd_in) {
    int read_size, iov_idx = 0;
    struct iovec iov[2];
    if (cbuf->fill_pos < cbuf->flush_pos) {
        read_size = read(fd_in, cbuf->fill_pos, cbuf->flush_pos - cbuf->fill_pos);
    }
    else {
        if (cbuf->fill_pos < cbuf->buf_end) {
            iov[iov_idx].iov_base = cbuf->fill_pos;
            iov[iov_idx].iov_len = cbuf->buf_end - cbuf->fill_pos;
            iov_idx += 1;
        }
        if (cbuf->buf < cbuf->flush_pos) {
            iov[iov_idx].iov_base = cbuf->buf;
            iov[iov_idx].iov_len = cbuf->flush_pos - cbuf->buf;
            iov_idx += 1;
        }
        read_size = readv(fd_in, iov, iov_idx);
        debug_printf("readv fd=%d result=%d\n", fd_in, read_size);
    }
    if (read_size == -1) {
        return -1;
    }
    cbuf->fill_pos += read_size;
    if (cbuf->fill_pos >= cbuf->buf_end) {
        cbuf->fill_pos -= cbuf->size;
    }
    cbuf->level += read_size;
    return 0;
}

int cbuf_flush(circular_buffer_t *cbuf, int size, struct iovec *iovecs) {
    int iov_idx = 0, init_size = size;
    if (cbuf->fill_pos > cbuf->flush_pos) {
        iovecs[iov_idx].iov_base = cbuf->flush_pos;
        iovecs[iov_idx].iov_len = size;
        iov_idx += 1;
    }
    else {
        iovecs[iov_idx].iov_base = cbuf->flush_pos;
        if (size <= cbuf->buf_end - cbuf->flush_pos) {
            iovecs[iov_idx].iov_len = size;
        }
        else {
            iovecs[iov_idx].iov_len = cbuf->buf_end - cbuf->flush_pos;
        }
        size -= iovecs[iov_idx].iov_len;
        iov_idx += 1;
        if (size > 0) {
            iovecs[iov_idx].iov_base = cbuf->buf;
            iovecs[iov_idx].iov_len = size;
            iov_idx += 1;
        }
    }
    cbuf->flush_pos += init_size;
    if (cbuf->flush_pos >= cbuf->buf_end) {
        cbuf->flush_pos -= cbuf->size;
    }
    cbuf->level -= init_size;
    return iov_idx;
}

void cbuf_pass(circular_buffer_t *cbuf, int shift) {
    cbuf->flush_pos += shift;
    if (cbuf->flush_pos >= cbuf->buf_end) {
        cbuf->flush_pos -= cbuf->size;
    }
    cbuf->level -= shift;
}

int cbuf_peek_big_endian_short(circular_buffer_t *cbuf) {
    int i1 = *(cbuf->flush_pos), i0;
    if (cbuf->flush_pos + 1 == cbuf->buf_end) {
        i0 = *(cbuf->buf);
    }
    else {
        i0 = *(cbuf->flush_pos + 1);
    }
    return (i1 << 8) + i0;
}

int cbuf_empty(circular_buffer_t *cbuf) {
    return (cbuf->level == 0);
}

int cbuf_full(circular_buffer_t *cbuf) {
    return (cbuf->level == cbuf->size);
}

int cbuf_available(circular_buffer_t *cbuf) {
    return cbuf->size - cbuf->level;
}

#define UDP_PAYLOAD_MAX_SIZE    4096    /* ensured by interface MTU, see comment in const.py */
#define BUFFER_LENGTHS_SIZE     256
#define LENGTH_SIZE             2       /* size to encode packet length */
#define PACKET_BATCH_SIZE       32
#define BUFFER_PACKETS_SIZE     (UDP_PAYLOAD_MAX_SIZE << 5)    /* 32 times UDP_PAYLOAD_MAX_SIZE */

int client_transmission_loop(int lengths_stdin, int lengths_stdout,
                             int packets_stdin, int packets_stdout, int sock_fd) {
    unsigned char buf_len[PACKET_BATCH_SIZE * LENGTH_SIZE], *plen;
    int num_msgs, num_iovecs, res, max_fd, i;
    ssize_t packet_len, total_size;
    fd_set fds, init_fds;
    circular_buffer_t lengths_buf, packets_buf;
    struct mmsghdr recv_msgs[PACKET_BATCH_SIZE],
                   send_msgs[PACKET_BATCH_SIZE];
    /* send_iovecs will be used on a circular buffer, 2*PACKET_BATCH_SIZE is
     * a worst case scenario. */
    struct iovec recv_iovecs[PACKET_BATCH_SIZE],
                 send_iovecs[2*PACKET_BATCH_SIZE];
#ifdef DEBUG
    int max_packet_len = 0;
#endif

    /* when reading on ssh stdout, we are reading a continuous flow */
    cbuf_setup(&lengths_buf, BUFFER_LENGTHS_SIZE);
    cbuf_setup(&packets_buf, BUFFER_PACKETS_SIZE);

    redirect_sigint();

    memset(recv_msgs, 0, sizeof(recv_msgs));
    for (i = 0; i < PACKET_BATCH_SIZE; i++) {
        recv_iovecs[i].iov_base         = malloc(sizeof(unsigned char) * UDP_PAYLOAD_MAX_SIZE);
        recv_iovecs[i].iov_len          = UDP_PAYLOAD_MAX_SIZE;
        recv_msgs[i].msg_hdr.msg_iov         = &recv_iovecs[i];
        recv_msgs[i].msg_hdr.msg_iovlen      = 1;
    }
    memset(send_msgs, 0, sizeof(send_msgs));

    FD_ZERO(&init_fds);
    FD_SET(lengths_stdout, &init_fds);
    FD_SET(packets_stdout, &init_fds);
    FD_SET(sock_fd, &init_fds);
    max_fd = MAX(MAX(lengths_stdout, packets_stdout), sock_fd) + 1;

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
            /* read multiple UDP packets */
            num_msgs = recvmmsg(sock_fd, recv_msgs, PACKET_BATCH_SIZE, MSG_DONTWAIT, NULL);
            if (num_msgs == -1) {
                perror("recvmmsg()");
                status = STOPPED_SHOULD_REINIT;
                break;
            }
            /* prepare next writes */
            total_size = 0;
            for (i = 0, plen = buf_len; i < num_msgs; ++i, plen += LENGTH_SIZE) {
                packet_len = recv_msgs[i].msg_len;
#ifdef DEBUG
                if (packet_len > max_packet_len) {
                    max_packet_len = packet_len;
                    debug_printf("** max_packet_len %d **\n", max_packet_len);
                }
#endif
                debug_printf("client -> server %d bytes\n", (int)packet_len);

                store_packet_len(plen, packet_len);
                send_iovecs[i].iov_base = recv_iovecs[i].iov_base;
                send_iovecs[i].iov_len = packet_len;
                total_size += packet_len;
            }
            /* write packets length */
            res = write_fd(lengths_stdin, buf_len, plen, "ssh lengths channel");
            if (res == -1) {
                status = STOPPED_SHOULD_REINIT;
                break;
            }
            /* write packets content */
            res = writev(packets_stdin, send_iovecs, num_msgs);
            if (res == -1) {
                perror("writev()");
                status = STOPPED_SHOULD_REINIT;
                break;
            }
            if (res < total_size) {
                debug_printf("partial writev %d/%d\n", res, (int)total_size);
                status = STOPPED_SHOULD_ABORT;
                break;
            }
        }
        else if (FD_ISSET(lengths_stdout, &fds)) {
            debug_printf("lengths_stdout input\n");
            cbuf_fill(&lengths_buf, lengths_stdout);
        }
        else {  // packets_stdout fd is set
            debug_printf("packets_stdout input\n");
            cbuf_fill(&packets_buf, packets_stdout);
        }

        /* look for complete packets and prepare sendmmsg() */
        i = 0;
        num_msgs = 0;
        while ((lengths_buf.level >= LENGTH_SIZE) && (packets_buf.level > 0) && \
               (num_msgs < PACKET_BATCH_SIZE)) {
            packet_len = cbuf_peek_big_endian_short(&lengths_buf);
            if (packets_buf.level < packet_len) {
                break; // packet not fully obtained
            }
#ifdef DEBUG
            if (packet_len > max_packet_len) {
                max_packet_len = packet_len;
                debug_printf("** max_packet_len %d **\n", max_packet_len);
            }
#endif
            debug_printf("server -> client %d bytes\n", (int)packet_len);
            /* add to send_iovecs for this UDP packet */
            num_iovecs = cbuf_flush(&packets_buf, packet_len, send_iovecs + i);
            send_msgs[num_msgs].msg_hdr.msg_iov         = send_iovecs + i;
            send_msgs[num_msgs].msg_hdr.msg_iovlen      = num_iovecs;
            num_msgs += 1;
            i += num_iovecs;
            /* pass packet length */
            cbuf_pass(&lengths_buf, LENGTH_SIZE);
        }

        /* send complete packets if any */
        if (num_msgs > 0) {
            res = sendmmsg(sock_fd, send_msgs, num_msgs, 0);
            debug_printf("sendmmsg num_msgs=%d result=%d\n", num_msgs, res);
            if (res == -1) {
                perror("sendmmsg()");
                status = STOPPED_SHOULD_REINIT;
                break;
            }
            if (res < num_msgs) {
                printf("incomplete sendmmsg()\n");
                status = STOPPED_SHOULD_ABORT;
                break;
            }
        }

        /* stop reading when buffer has no more room for a new packet */
        if (cbuf_available(&lengths_buf) < LENGTH_SIZE) {
            FD_CLR(lengths_stdout, &init_fds);
        }
        else {
            FD_SET(lengths_stdout, &init_fds);
        }

        debug_printf("cbuf_available(&packets_buf) = %d\n", cbuf_available(&packets_buf));
        if (cbuf_available(&packets_buf) < UDP_PAYLOAD_MAX_SIZE) {
            FD_CLR(packets_stdout, &init_fds);
        }
        else {
            FD_SET(packets_stdout, &init_fds);
        }
    }
    cbuf_release(&lengths_buf);
    cbuf_release(&packets_buf);
    for (i = 0; i < PACKET_BATCH_SIZE; i++) {
        free(recv_iovecs[i].iov_base);
    }
    assert(status != RUNNING);
    return (status == STOPPED_SHOULD_REINIT);
}

#define SERVER_SOCK_FD  3
#define L2TP_SOCK_FD    4
#define PACKET_BUFFER_SIZE  (LENGTH_SIZE + UDP_PAYLOAD_MAX_SIZE)

static inline uint32_t l2tp_parse_session_id(unsigned char *l2tp_packet) {
    /* session ID is defined as a 32-bit unsigned integer on bytes 4 to 7 of L2TP header */
    return ntohl(*((uint32_t*)(l2tp_packet+4)));
}

void server_transmission_loop(int(*on_connect)(), int(*on_disconnect)(int fd_range_start)) {
    unsigned char *buf, *packet;
    unsigned char buf_len[LENGTH_SIZE];
    int res, max_fd, init_max_fd, fd, fd_range_start, ep_lengths_stdin_fd, ep_lengths_stdout_fd,
        ep_packets_stdin_fd, ep_packets_stdout_fd;
    ssize_t packet_len;
    fd_set fds, init_fds;

    buf = malloc(PACKET_BUFFER_SIZE * sizeof(unsigned char));
    packet = buf + LENGTH_SIZE;

    redirect_sigint();

    FD_ZERO(&init_fds);
    FD_SET(SERVER_SOCK_FD, &init_fds);
    FD_SET(L2TP_SOCK_FD, &init_fds);
    init_max_fd = L2TP_SOCK_FD;

    /* start select loop
     * python handles the smart part of the code and ensures that
     * each client is associated with a range of 8 consecutive file descriptors.
     * see comment on top of server.py */

    status = RUNNING;
    while (status == RUNNING) {
        fds = init_fds;
        max_fd = init_max_fd;
        debug_printf("select()");
        res = select(max_fd + 1, &fds, NULL, NULL, NULL);
        if (res < 1) {
            perror("select error");
            break;
        }
        for (fd = SERVER_SOCK_FD; fd <= max_fd; ++fd) {
            if (FD_ISSET(fd, &fds)) {
                if (fd == SERVER_SOCK_FD) {
                    fd_range_start = on_connect();
                    if (fd_range_start == -1) {
                        status = STOPPED_SHOULD_ABORT;
                        break;
                    }
                    if (fd_range_start == 0) {
                        /* we got 1st client stream, we need the 2nd one,
                         * nothing to do for now */
                        continue;
                    }
                    ep_lengths_stdin_fd = fd_range_start +0;
                    ep_packets_stdin_fd = fd_range_start +3;
                    printf("new client fd_range_start=%d\n", fd_range_start);
                    FD_SET(ep_lengths_stdin_fd, &init_fds);
                    if (ep_packets_stdin_fd > init_max_fd) {
                        init_max_fd = ep_packets_stdin_fd;
                    }
                }
                else {
                    debug_printf("event on fd=%d\n", fd);
                    res = 0;    // ok, up to now
                    if (fd == L2TP_SOCK_FD) { // packet on L2TP UDP socket
                        /* read data from L2TP socket */
                        res = read_fd_once(L2TP_SOCK_FD, packet, UDP_PAYLOAD_MAX_SIZE, &packet_len, "l2tp socket");
                        if (res == -1) {
                            status = STOPPED_SHOULD_ABORT;
                            break;
                        }
                        /* read session id from L2TP header
                         * note: L2TP sessions are established using session ID = fd_range_start */
                        fd_range_start = (int)l2tp_parse_session_id(packet);
                        ep_lengths_stdout_fd = fd_range_start +1;
                        ep_packets_stdout_fd = fd_range_start +4;
                        debug_printf("found session_id=%d\n", fd_range_start);
                        /* write packet len */
                        store_packet_len(buf_len, packet_len);
                        res = write_fd(ep_lengths_stdout_fd, buf_len, buf_len + LENGTH_SIZE, "ssh lengths channel");
                        if (res == 0) {
                            /* write packet content */
                            debug_printf("server -> client %ld bytes\n", packet_len);
                            res = write_fd(ep_packets_stdout_fd, packet, packet + packet_len, "ssh packets channel");
                        }
                    }
                    else { // not L2TP_SOCK_FD => ep_lengths_stdin_fd
                        fd_range_start = fd;
                        ep_lengths_stdin_fd = fd;
                        ep_packets_stdin_fd = fd_range_start + 3;
                        /* read packet length as 2 bytes */
                        res = read_fd(ep_lengths_stdin_fd, buf, LENGTH_SIZE, "ssh lengths channel");
                        if (res == 0) {
                            packet_len = compute_packet_len(buf);
                            /* read packet data */
                            res = read_fd(ep_packets_stdin_fd, packet, packet_len, "ssh packets channel");
                        }
                        if (res == 0) {
                            /* write packet to L2TP socket */
                            debug_printf("client -> server %ld bytes\n", packet_len);
                            res = write_fd(L2TP_SOCK_FD, packet, packet + packet_len, "l2tp socket");
                        }
                    }
                    if (res == -1) {
                        // client issue, disconnect
                        ep_lengths_stdin_fd = fd_range_start;
                        printf("disconnecting client fd_range_start=%d error=%s\n", fd_range_start, strerror(errno));
                        FD_CLR(ep_lengths_stdin_fd, &init_fds);
                        /* since we continue the loop on fds, avoid catching errors
                           on ep_lengths_stdin_fd of the same client which we are disconnecting. */
                        if (fd == L2TP_SOCK_FD) {
                            FD_CLR(ep_lengths_stdin_fd, &fds); /* note: "&fds" here, not "&init_fds" */
                        }
                        init_max_fd = on_disconnect(fd_range_start);
                        if (init_max_fd == -1) {
                            status = STOPPED_SHOULD_ABORT;
                            break;
                        }
                    }
                }
            }
        }
    }
    free(buf);
}
