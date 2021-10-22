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

int client_transmission_loop(int ssh_stdin, int ssh_stdout, int tap_fd) {
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
    FD_SET(ssh_stdout, &init_fds);
    FD_SET(tap_fd, &init_fds);
    max_fd = MAX(ssh_stdout, tap_fd) + 1;

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
            res = write_fd(ssh_stdin, buf_tap_to_ssh, pos_tap_to_ssh + sres,
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

            res = read_fd_once(ssh_stdout, read_pos_ssh_to_tap, max_read,
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

#define ENDPOINT_STDIN  0
#define ENDPOINT_STDOUT 1

void endpoint_transmission_loop(int sock_fd) {
    unsigned char *buf;
    int res, max_fd, r_fd, w_fd;
    ssize_t sres;
    fd_set fds, init_fds;

    buf = malloc(BUFFER_SIZE * sizeof(unsigned char));

    redirect_sigint();

    FD_ZERO(&init_fds);
    FD_SET(ENDPOINT_STDIN, &init_fds);
    FD_SET(sock_fd, &init_fds);
    max_fd = sock_fd + 1;

    /* start select loop
       we will just copy:
       * all data from socket to stdout
       * all data from stdin to socket
    */
    status = RUNNING;
    while (status == RUNNING) {
        fds = init_fds;
        res = select(max_fd, &fds, NULL, NULL, NULL);
        if (res < 1) {
            perror("select error");
            break;
        }
        if (FD_ISSET(sock_fd, &fds)) {
            r_fd = sock_fd;
            w_fd = ENDPOINT_STDOUT;
        }
        else {
            r_fd = ENDPOINT_STDIN;
            w_fd = sock_fd;
        }
        /* read data */
        res = read_fd_once(r_fd, buf, BUFFER_SIZE, &sres, NULL);
        if (res == -1) {
            status = STOPPED_SHOULD_ABORT;
            break;
        }
        /* write to the other end */
        res = write_fd(w_fd, buf, buf + sres, NULL);
        if (res == -1) {
            status = STOPPED_SHOULD_ABORT;
            break;
        }
    }
    free(buf);
}

#define SERVER_SOCK_FD  3
//#define DEBUG
#ifdef DEBUG
#define debug_printf printf
#else
#define debug_printf(...)   /* do nothing */
#endif

void server_transmission_loop(int(*on_connect)(), int(*on_disconnect)(int tap_fd)) {
    unsigned char *buf, *packet;
    int res, max_fd, init_max_fd, fd, sock_fd, tap_fd;
    ssize_t packet_len;
    fd_set fds, init_fds;

    buf = malloc(PACKET_BUFFER_SIZE * sizeof(unsigned char));
    packet = buf + LENGTH_SIZE;

    redirect_sigint();

    FD_ZERO(&init_fds);
    FD_SET(SERVER_SOCK_FD, &init_fds);
    init_max_fd = SERVER_SOCK_FD;

    /* start select loop
       we will just:
       * accept all clients that connect to /var/run/walt-vpn.sock
       * for each client create a tap and add it to walt-net
       * transfer packets coming from a client socket to the corresponding tap interface
       * transfer packets coming from a tap interface to the corresponding client socket
       client code management is delegated to python using on_connect() and on_disconnect()
       callbacks.
       python code ensures that the tap file descriptor of each client is an
       even number and the corresponding socket file descriptor is the odd number
       immediately following.
    */
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
                    tap_fd = on_connect();
                    if (tap_fd == -1) {
                        status = STOPPED_SHOULD_ABORT;
                        break;
                    }
                    sock_fd = tap_fd +1;
                    printf("new client tap_fd=%d sock_fd=%d\n", tap_fd, sock_fd);
                    FD_SET(tap_fd, &init_fds);
                    FD_SET(sock_fd, &init_fds);
                    if (sock_fd > init_max_fd) {
                        init_max_fd = sock_fd;
                    }
                }
                else {
                    debug_printf("event on fd=%d\n", fd);
                    res = 0;    // ok, up to now
                    if ((fd & 0x1) == 0) { // even number => tap
                        tap_fd = fd;
                        sock_fd = fd + 1;
                        /* read data from tap */
                        res = read_fd_once(tap_fd, packet, ETHERNET_MAX_SIZE, &packet_len, "tap");
                        if (res == 0) {
                            /* prefix with packet len */
                            store_packet_len(buf, packet_len);
                            /* write to the socket */
                            debug_printf("writing packet of %ld bytes to socket\n", packet_len);
                            res = write_fd(sock_fd, buf, buf + (LENGTH_SIZE + packet_len), "socket");
                        }
                    }
                    else { // odd number => socket
                        tap_fd = fd - 1;
                        sock_fd = fd;
                        /* read packet length as 2 bytes */
                        res = read_fd(sock_fd, buf, LENGTH_SIZE, "socket");
                        if (res == 0) {
                            packet_len = compute_packet_len(buf);
                            /* read packet data */
                            res = read_fd(sock_fd, packet, packet_len, "socket");
                        }
                        if (res == 0) {
                            /* write packet on tap */
                            debug_printf("writing packet of %ld bytes to tap\n", packet_len);
                            res = write_fd(tap_fd, packet, packet + packet_len, "tap");
                        }
                    }
                    if (res == -1) {
                        // client issue, disconnect
                        printf("disconnecting client tap_fd=%d sock_fd=%d error=%s\n",
                               tap_fd, sock_fd, strerror(errno));
                        FD_CLR(tap_fd, &init_fds);
                        FD_CLR(sock_fd, &init_fds);
                        /* since we continue the loop on fds, avoid catching errors
                           on next file descriptor sock_fd: it is bound to the same
                           client which we are disconnecting. */
                        if (fd == tap_fd) {
                            FD_CLR(sock_fd, &fds);
                        }
                        init_max_fd = on_disconnect(tap_fd);
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
