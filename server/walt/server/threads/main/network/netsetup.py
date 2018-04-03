class NetSetup(int):
    def __new__(cls, name):
        if isinstance(name, int) and 0 <= name <= 1:
            return super(NetSetup, cls).__new__(cls, name)
        elif str(name).upper() == "LAN":
            return super(NetSetup, cls).__new__(cls, cls.LAN)
        elif str(name).upper() == "NAT":
            return super(NetSetup, cls).__new__(cls, cls.NAT)
        raise ValueError

    def readable_string(self):
        if self == self.LAN:
            return "LAN"
        else:
            return "NAT"

    LAN = 0
    NAT = 1
