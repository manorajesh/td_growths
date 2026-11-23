"""
Send one OSC message (for testing the spores switch, or anything else).  No dependencies.

    python3 helper/osc_send.py /growth/enable 1                # value
    python3 helper/osc_send.py /growth/enable                  # no value = a 'bang' pulse
    python3 helper/osc_send.py /growth/enable 1 --pulse 0.2    # 1, wait 0.2 s, 0  (a pulse)
    python3 helper/osc_send.py /growth/enable/off --host 192.168.1.20 --port 7000
"""
import argparse
import socket
import struct
import time


def _pad(b):
	return b + b'\0' * (4 - len(b) % 4)


def message(address, args):
	tags, data = ',', b''
	for a in args:
		if isinstance(a, float):
			tags += 'f'
			data += struct.pack('>f', a)
		elif isinstance(a, int):
			tags += 'i'
			data += struct.pack('>i', a)
		else:
			tags += 's'
			data += _pad(str(a).encode())
	return _pad(address.encode()) + _pad(tags.encode()) + data


def parse(v):
	for t in (int, float):
		try:
			return t(v)
		except ValueError:
			pass
	return v


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument('address')
	ap.add_argument('values', nargs='*')
	ap.add_argument('--host', default='127.0.0.1')
	ap.add_argument('--port', type=int, default=7000)
	ap.add_argument('--pulse', type=float, default=0, help='send the value, then 0 after this many seconds')
	a = ap.parse_args()
	s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	args = [parse(v) for v in a.values]
	s.sendto(message(a.address, args), (a.host, a.port))
	print('sent', a.address, *args, '->', '{}:{}'.format(a.host, a.port))
	if a.pulse > 0:
		time.sleep(a.pulse)
		s.sendto(message(a.address, [0]), (a.host, a.port))
		print('sent', a.address, 0)


if __name__ == '__main__':
	main()
