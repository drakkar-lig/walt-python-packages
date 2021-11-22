#include <sys/select.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/uio.h>
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
#include <time.h>
#include <signal.h>
#include <errno.h>
#include <stdlib.h>
#include <assert.h>
#include <string.h>

//#define DEBUG
#ifdef DEBUG
#define debug_printf(...) fprintf(stderr, __VA_ARGS__)
#else
#define debug_printf(...)   /* do nothing */
#endif

#define MIN(i, j) (((i) > (j))?(j):(i))
#define MAX(i, j) (((i) > (j))?(i):(j))

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

static inline int write_fd(int fd, unsigned char *start, unsigned char *end,
                            char *fd_label) {
    ssize_t sres;
    while (start < end) {
        sres = write(fd, start, end - start);
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
        iov[iov_idx].iov_base = cbuf->fill_pos;
        iov[iov_idx].iov_len = cbuf->flush_pos - cbuf->fill_pos;
        iov_idx += 1;
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
    }
    read_size = readv(fd_in, iov, iov_idx);
    if (read_size > 0) {
        cbuf->fill_pos += read_size;
        if (cbuf->fill_pos >= cbuf->buf_end) {
            cbuf->fill_pos -= cbuf->size;
        }
        cbuf->level += read_size;
        return 0;
    }
    if (read_size == 0) {
        fprintf(stderr, "Empty read.\n");
    }
    return -1;
}

int cbuf_flush(circular_buffer_t *cbuf, int size, int fd_out) {
    int write_size, iov_idx = 0;
    struct iovec iov[2];
    if (cbuf->fill_pos > cbuf->flush_pos) {
        iov[iov_idx].iov_base = cbuf->flush_pos;
        iov[iov_idx].iov_len = size;
        iov_idx += 1;
    }
    else {
        iov[iov_idx].iov_base = cbuf->flush_pos;
        if (size <= cbuf->buf_end - cbuf->flush_pos) {
            iov[iov_idx].iov_len = size;
        }
        else {
            iov[iov_idx].iov_len = cbuf->buf_end - cbuf->flush_pos;
        }
        size -= iov[iov_idx].iov_len;
        iov_idx += 1;
        if (size > 0) {
            iov[iov_idx].iov_base = cbuf->buf;
            iov[iov_idx].iov_len = size;
            iov_idx += 1;
        }
    }
    write_size = writev(fd_out, iov, iov_idx);
    if (write_size == -1) {
        return -1;
    }
    cbuf->flush_pos += write_size;
    if (cbuf->flush_pos >= cbuf->buf_end) {
        cbuf->flush_pos -= cbuf->size;
    }
    cbuf->level -= write_size;
    /* this is not necessary but in case of unnecessarily big buffers, it allows to
     * use the start of the buffer in most cases, thus it improves cache locality */
    if (cbuf->level == 0) {
        cbuf->fill_pos = cbuf->buf;
        cbuf->flush_pos = cbuf->buf;
    }
    return 0;
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

#define ETHERNET_MAX_SIZE   1514
#define BUFFER_SIZE_BITS    16
#define BUFFER_SIZE         (1<<BUFFER_SIZE_BITS)
#define BUFFER_LOOP_LIMIT_2 (BUFFER_SIZE - LENGTH_SIZE - ETHERNET_MAX_SIZE)
#define BUFFER_LOOP_LIMIT_1 (BUFFER_LOOP_LIMIT_2 - LENGTH_SIZE - ETHERNET_MAX_SIZE)
#define LENGTH_SIZE         2         /* size to encode packet length */
#define PACKET_BUFFER_SIZE  (LENGTH_SIZE + ETHERNET_MAX_SIZE)

/* packet length is encoded as 2 bytes, big endian */
static inline ssize_t compute_packet_len(unsigned char *len_pos) {
    return ((*len_pos) << 8) + *(len_pos+1);
}

static inline void store_packet_len(unsigned char *len_pos, ssize_t sres) {
    len_pos[0] = (unsigned char)(sres >> 8);
    len_pos[1] = (unsigned char)(sres & 0xff);
}

int ssh_tap_transfer_loop(int ssh_read_fd, int ssh_write_fd, int tap_fd) {
    unsigned char *buf_tap_to_ssh, *pos_tap_to_ssh;
    int res, max_fd;
    ssize_t sres, packet_len;
    fd_set fds, init_fds;
    circular_buffer_t buf_ssh_to_tap;

    /* when reading on tap, 1 read() means 1 packet */
    buf_tap_to_ssh = malloc((LENGTH_SIZE + ETHERNET_MAX_SIZE) * sizeof(unsigned char));
    pos_tap_to_ssh = buf_tap_to_ssh + LENGTH_SIZE;
    /* when reading on ssh stdout, we are reading a continuous flow */
    cbuf_setup(&buf_ssh_to_tap, BUFFER_SIZE);

    redirect_sigint();

    FD_ZERO(&init_fds);
    FD_SET(ssh_read_fd, &init_fds);
    FD_SET(tap_fd, &init_fds);
    max_fd = MAX(ssh_read_fd, tap_fd) + 1;

    /* start select loop
       we will:
       * transfer packets coming from the tap interface to ssh stdin
       * transfer packets coming from ssh stdout to the tap interface
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
        if (FD_ISSET(tap_fd, &fds)) {
            /* read new packet on tap */
            res = read_fd_once(tap_fd, pos_tap_to_ssh, ETHERNET_MAX_SIZE, &sres,
                             "tap");
            if (res == -1) {
                status = STOPPED_SHOULD_ABORT;
                break;
            }
            /* prefix packet length as 2 bytes, big endian */
            store_packet_len(buf_tap_to_ssh, sres);
            /* write packet to ssh stdin */
            res = write_fd(ssh_write_fd, buf_tap_to_ssh, pos_tap_to_ssh + sres,
                              "ssh channel");
            if (res == -1) {
                status = STOPPED_SHOULD_REINIT;
                break;
            }
        }
        else {
            /* we have to read network packets from ssh stdout, but these come as a
             * continuous data flow, and we have to write them on a tap interface,
             * with one write() per packet.
             * for efficiency, we read ssh stdout data into a buffer, which means
             * we read several packets at once, and reads might not be on packet
             * boundaries. */
            res = cbuf_fill(&buf_ssh_to_tap, ssh_read_fd);
            if (res == -1) {
                debug_printf("failure while reading ssh channel: %s\n", strerror(errno));
                status = STOPPED_SHOULD_REINIT;
                break;
            }

            /* write all complete packets to tap */
            while (buf_ssh_to_tap.level >= LENGTH_SIZE) {

                packet_len = cbuf_peek_big_endian_short(&buf_ssh_to_tap);
                if (buf_ssh_to_tap.level < LENGTH_SIZE + packet_len) {
                    break;  // not enough data
                }

                /* pass length field */
                cbuf_pass(&buf_ssh_to_tap, LENGTH_SIZE);

                /* write packet on tap */
                res = cbuf_flush(&buf_ssh_to_tap, packet_len, tap_fd);
                if (res == -1) {
                    status = STOPPED_SHOULD_ABORT;
                    break;
                }
            }
        }
    }
    free(buf_tap_to_ssh);
    cbuf_release(&buf_ssh_to_tap);
    assert(status != RUNNING);
    return (status == STOPPED_SHOULD_REINIT);
}

int client_transmission_loop(int ssh_stdin, int ssh_stdout, int tap_fd) {
    /* client runs a ssh process using subprocess.popen.
     * - ssh_stdin allows to write packets on the standard input of this process
     * - ssh_stdout allows to read packets transfered the other way and written
     *   on the standard output of this process */
    return ssh_tap_transfer_loop(ssh_stdout /* read from ssh channel */,
                                 ssh_stdin /* write to ssh channel */,
                                 tap_fd);
}

void endpoint_transmission_loop(int tap_fd) {
    /* the client runs ssh <options> walt-vpn@<server> walt-vpn-endpoint
     * (or, more precisely, walt-vpn-endpoint command is enforced by the
     * authorized_keys file)
     * - walt-vpn-endpoint stdin allows to read packets sent over the ssh
     *   channel from the client
     * - writting on walt-vpn-endpoint stdout allows to transfer packets
     *   the other way */
    ssh_tap_transfer_loop(0 /* stdin: read from ssh channel */,
                          1 /* stdout: write to ssh channel */,
                          tap_fd);
}
