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

#define DEBUG
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
    }
    if (read_size > 0) {
        cbuf->fill_pos += read_size;
        if (cbuf->fill_pos >= cbuf->buf_end) {
            cbuf->fill_pos -= cbuf->size;
        }
        cbuf->level += read_size;
        return read_size;
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
        write_size = write(fd_out, cbuf->flush_pos, size);
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
        write_size = writev(fd_out, iov, iov_idx);
    }
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

inline unsigned char *cbuf_pos_seek(circular_buffer_t *cbuf, unsigned char *pos, int shift) {
    pos += shift;
    if (pos >= cbuf->buf_end) {
        pos -= cbuf->size;
    }
    if (pos < cbuf->buf) {
        pos += cbuf->size;
    }
    return pos;
}

void cbuf_read_seek(circular_buffer_t *cbuf, int shift) {
    cbuf->flush_pos = cbuf_pos_seek(cbuf, cbuf->flush_pos, shift);
    cbuf->level -= shift;
}

void cbuf_write_seek(circular_buffer_t *cbuf, int shift) {
    cbuf->fill_pos = cbuf_pos_seek(cbuf, cbuf->fill_pos, shift);
    cbuf->level += shift;
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

inline void cbuf_write_unsigned_char(circular_buffer_t *cbuf, unsigned char c) {
    (*cbuf->fill_pos) = c;
    cbuf->fill_pos += 1;
    if (cbuf->fill_pos == cbuf->buf_end) {
        cbuf->fill_pos = cbuf->buf;
    }
    cbuf->level += 1;
}

void cbuf_write_big_endian_short(circular_buffer_t *cbuf, int n) {
    int i1 = (n >> 8), i0 = (n & 0xff);
    cbuf_write_unsigned_char(cbuf, i1);
    cbuf_write_unsigned_char(cbuf, i0);
}

int cbuf_empty(circular_buffer_t *cbuf) {
    return (cbuf->level == 0);
}

int cbuf_full(circular_buffer_t *cbuf) {
    return (cbuf->level == cbuf->size);
}

int cbuf_has_enough_room(circular_buffer_t *cbuf, int expected) {
    return (cbuf->size - cbuf->level) >= expected;
}

#define ETHERNET_MAX_SIZE   1514
#define BUFFER_SIZE_BITS    16
#define BUFFER_SIZE         (1<<BUFFER_SIZE_BITS)
#define LENGTH_SIZE         2         /* size to encode packet length */
#define FULL_PACKET_SIZE    (LENGTH_SIZE + ETHERNET_MAX_SIZE)

/* packet length is encoded as 2 bytes, big endian */
static inline ssize_t compute_packet_len(unsigned char *len_pos) {
    return ((*len_pos) << 8) + *(len_pos+1);
}

static inline void store_packet_len(unsigned char *len_pos, ssize_t sres) {
    len_pos[0] = (unsigned char)(sres >> 8);
    len_pos[1] = (unsigned char)(sres & 0xff);
}

static inline void cond_fd_set(int fd, fd_set *set, int cond) {
    if (cond) {
        FD_SET(fd, set);
    }
    else {
        FD_CLR(fd, set);
    }
}

int ssh_tap_transfer_loop(int ssh_read_fd, int ssh_write_fd, int tap_fd) {
    int res, max_fd, full_packet_ready_for_tap;
    ssize_t packet_len;
    fd_set rfds, wfds;
    circular_buffer_t buf_ssh_to_tap, buf_tap_to_ssh;

    cbuf_setup(&buf_ssh_to_tap, BUFFER_SIZE);
    cbuf_setup(&buf_tap_to_ssh, BUFFER_SIZE);

    redirect_sigint();

    FD_ZERO(&rfds);
    FD_SET(ssh_read_fd, &rfds);
    FD_SET(tap_fd, &rfds);
    FD_ZERO(&wfds);
    max_fd = MAX(MAX(ssh_read_fd, ssh_write_fd), tap_fd) + 1;

    /* start select loop
       we will:
       * transfer packets coming from the tap interface to ssh stdin
       * transfer packets coming from ssh stdout to the tap interface
    */
    status = RUNNING;
    while (status == RUNNING) {
        res = select(max_fd, &rfds, &wfds, NULL, NULL);
        if (res < 1) {
            perror("select error");
            status = STOPPED_SHOULD_REINIT;  // caller should reinit
            break;
        }

        if (FD_ISSET(tap_fd, &rfds)) {
            /* incomping packet on tap */
            /* save room for packet length on buffer */
            cbuf_write_seek(&buf_tap_to_ssh, LENGTH_SIZE);
            /* read new packet on tap */
            packet_len = cbuf_fill(&buf_tap_to_ssh, tap_fd);
            if (packet_len == -1) {
                debug_printf("failure while reading tap: %s\n", strerror(errno));
                status = STOPPED_SHOULD_ABORT;
                break;
            }
            /* return to packet length position on buffer */
            cbuf_write_seek(&buf_tap_to_ssh, - packet_len - LENGTH_SIZE);
            /* prefix packet length as 2 bytes, big endian */
            cbuf_write_big_endian_short(&buf_tap_to_ssh, packet_len);
            /* return to end of packet */
            cbuf_write_seek(&buf_tap_to_ssh, packet_len);
        }

        if (FD_ISSET(ssh_read_fd, &rfds)) {
            /* incoming data from ssh channel */
            res = cbuf_fill(&buf_ssh_to_tap, ssh_read_fd);
            if (res == -1) {
                debug_printf("failure while reading ssh channel: %s\n", strerror(errno));
                status = STOPPED_SHOULD_REINIT;
                break;
            }
        }

        if (FD_ISSET(ssh_write_fd, &wfds)) {
            /* there is room on ssh channel write buffer */
            res = cbuf_flush(&buf_tap_to_ssh, buf_tap_to_ssh.level /* whole buffer */, ssh_write_fd);
            if (res == -1) {
                debug_printf("failure while writing ssh channel: %s\n", strerror(errno));
                status = STOPPED_SHOULD_REINIT;
                break;
            }
        }

        if (FD_ISSET(tap_fd, &wfds)) {
            packet_len = cbuf_peek_big_endian_short(&buf_ssh_to_tap);
            /* pass length field */
            cbuf_read_seek(&buf_ssh_to_tap, LENGTH_SIZE);
            /* write packet on tap */
            res = cbuf_flush(&buf_ssh_to_tap, packet_len, tap_fd);
            if (res == -1) {
                status = STOPPED_SHOULD_ABORT;
                break;
            }
        }

        /* check which conditions the next select() should match */
        cond_fd_set(tap_fd, &rfds, cbuf_has_enough_room(&buf_tap_to_ssh, FULL_PACKET_SIZE));
        cond_fd_set(ssh_read_fd, &rfds, !cbuf_full(&buf_ssh_to_tap));
        cond_fd_set(ssh_write_fd, &wfds, !cbuf_empty(&buf_tap_to_ssh));

        full_packet_ready_for_tap = 0;
        if (buf_ssh_to_tap.level > LENGTH_SIZE) {
            packet_len = cbuf_peek_big_endian_short(&buf_ssh_to_tap);
            if (buf_ssh_to_tap.level >= LENGTH_SIZE + packet_len) {
                full_packet_ready_for_tap = 1;
            }
        }
        cond_fd_set(tap_fd, &wfds, full_packet_ready_for_tap);
    }
    cbuf_release(&buf_ssh_to_tap);
    cbuf_release(&buf_tap_to_ssh);
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
