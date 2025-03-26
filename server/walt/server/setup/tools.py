import sys
import time


def wait_message_read():
    print(" " * 71 + "]\r[", end="")
    sys.stdout.flush()
    for i in range(70):
        print("*", end="")
        sys.stdout.flush()
        time.sleep(0.28)
    print("\r" + " " * 72 + "\r", end="")
    sys.stdout.flush()
