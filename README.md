# py3status
Statusline generator for i3bar

# Dependencies
python-psutil

python-alsaaaudio for Python3

python-mpd2

hddtemp running as daemon

Put the conf file in your home, edit it for your tastes and you are
set.

# Possible tripwires:

**HDDTemp thread** - I don't know how hddtemp behaves in the presence of
2 or more hard drives, feedback appreciated

**Nvidia temperature check** - Untested, should work

**WirelessStatus** - Drivers that do not support ioctl calls will not work
