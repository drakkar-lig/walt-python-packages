#include <sys/select.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
#include <time.h>
#include <signal.h>
#include <errno.h>
#include <stdlib.h>
#include <assert.h>
#include <string.h>

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
    unsigned char *buf_tap_to_ssh, *buf_ssh_to_tap, *pos_tap_to_ssh,
                  *len_pos_ssh_to_tap, *read_pos_ssh_to_tap, *limit1_ssh_to_tap,
                  *limit2_ssh_to_tap, *end_packet;
    int res, max_fd;
    ssize_t sres, packet_len, read_len_ssh_to_tap, max_read;
    fd_set fds, init_fds;

    /* when reading on tap, 1 read() means 1 packet */
    buf_tap_to_ssh = malloc((LENGTH_SIZE + ETHERNET_MAX_SIZE) * sizeof(unsigned char));
    pos_tap_to_ssh = buf_tap_to_ssh + LENGTH_SIZE;
    /* when reading on ssh stdout, we are reading a continuous flow */
    buf_ssh_to_tap = malloc(BUFFER_SIZE * sizeof(unsigned char));
    read_len_ssh_to_tap = 0;
    len_pos_ssh_to_tap = buf_ssh_to_tap;
    read_pos_ssh_to_tap = buf_ssh_to_tap;
    limit1_ssh_to_tap = buf_ssh_to_tap + BUFFER_LOOP_LIMIT_1;
    limit2_ssh_to_tap = buf_ssh_to_tap + BUFFER_LOOP_LIMIT_2;

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
             * boundaries.
             * "several packets at once" means we set the maximum read size to match
             * the end of the buffer minus the maximum packet size. ("limit 2")
             * when getting near the end of the buffer, we handle the last packet
             * differently: we ensure we will not read beyond the end of this packet.
             * then, for next packets, we can resume the process from the start of
             * the buffer.
             * "near the end of the buffer" means twice the maximum packet size from
             * the end. ("limit 1") */
            if (read_pos_ssh_to_tap < limit1_ssh_to_tap) {   // read standard packet
                max_read = limit2_ssh_to_tap - read_pos_ssh_to_tap;
            }
            else if (read_len_ssh_to_tap < LENGTH_SIZE) {   // read length of last packet in buffer
                max_read = LENGTH_SIZE - read_len_ssh_to_tap;
            }
            else {  // read data of last packet in buffer
                packet_len = compute_packet_len(len_pos_ssh_to_tap);
                max_read = LENGTH_SIZE + packet_len - read_len_ssh_to_tap;
            }

            res = read_fd_once(ssh_read_fd, read_pos_ssh_to_tap, max_read,
                         &sres, "ssh channel");
            if (res == -1) {
                status = STOPPED_SHOULD_REINIT;
                break;
            }

            read_len_ssh_to_tap += sres;
            read_pos_ssh_to_tap += sres;

            /* write all complete packets to tap */
            while (1) {
                if (read_len_ssh_to_tap < LENGTH_SIZE) {
                    break;  // not enough data
                }

                packet_len = compute_packet_len(len_pos_ssh_to_tap);
                if (read_len_ssh_to_tap < LENGTH_SIZE + packet_len) {
                    break;  // not enough data
                }

                /* write packet on tap */
                end_packet = len_pos_ssh_to_tap + LENGTH_SIZE + packet_len;
                res = write_fd(tap_fd, len_pos_ssh_to_tap + LENGTH_SIZE, end_packet,
                                  "tap");
                if (res == -1) {
                    status = STOPPED_SHOULD_ABORT;
                    break;
                }

                /* update pointers for next packet */
                read_len_ssh_to_tap -= LENGTH_SIZE + packet_len;
                if (read_len_ssh_to_tap == 0) {
                    /* we have read up to the packet boundary
                     * => we can return to the start of the buffer */
                    read_pos_ssh_to_tap = buf_ssh_to_tap;
                    len_pos_ssh_to_tap = buf_ssh_to_tap;
                }
                else {
                    /* jump to next packet */
                    len_pos_ssh_to_tap += LENGTH_SIZE + packet_len;
                }
            }
        }
    }
    free(buf_tap_to_ssh);
    free(buf_ssh_to_tap);
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
