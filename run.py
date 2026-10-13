"""Start the built frontend and API on one LAN port."""
import argparse
import ipaddress
import platform
from pathlib import Path
import shutil
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def local_ip():
    def lan_address(value):
        try:
            address = ipaddress.ip_address(value)
            return any(address in network for network in (
                ipaddress.ip_network('10.0.0.0/8'),
                ipaddress.ip_network('172.16.0.0/12'),
                ipaddress.ip_network('192.168.0.0/16'),
            ))
        except ValueError:
            return False

    # On macOS, use the actual Ethernet/Wi-Fi interface instead of a VPN route.
    if platform.system() == 'Darwin':
        for _, interface in socket.if_nameindex():
            if interface.startswith('en'):
                result = subprocess.run(['/usr/sbin/ipconfig', 'getifaddr', interface], capture_output=True, text=True)
                address = result.stdout.strip()
                if lan_address(address):
                    return address
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(('192.168.1.1', 1))
            address = sock.getsockname()[0]
            if lan_address(address):
                return address
        for result in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            if lan_address(result[4][0]):
                return result[4][0]
    except OSError:
        pass
    return '你的电脑局域网IP'


def main():
    parser = argparse.ArgumentParser(description='针线小账 · 局域网启动')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--reload', action='store_true')
    parser.add_argument('--build', action='store_true', help='启动前重新构建前端')
    args = parser.parse_args()
    if args.build or not (ROOT / 'frontend/dist/index.html').is_file():
        npm = shutil.which('npm')
        if not npm:
            sys.exit('缺少前端构建。安装 Node.js 后在 frontend 中运行 npm install 和 npm run build。')
        if not (ROOT / 'frontend/node_modules').is_dir():
            subprocess.run([npm, 'ci'], cwd=ROOT / 'frontend', check=True)
        subprocess.run([npm, 'run', 'build'], cwd=ROOT / 'frontend', check=True)
    print(f'\n电脑访问：http://127.0.0.1:{args.port}', flush=True)
    print(f'手机访问：http://{local_ip()}:{args.port}  （手机和电脑连接同一个 Wi-Fi）\n', flush=True)
    import uvicorn
    uvicorn.run('backend.main:app', host=args.host, port=args.port, reload=args.reload)


if __name__ == '__main__':
    main()
