"""Native macOS launcher: local dependencies, one port and browser handoff."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.identity import instance_id
from run import local_ip

NODE_VERSION = '22.23.0'
DIRECT_HTTP = build_opener(ProxyHandler({}))


def read_json(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False))
    temporary.replace(path)


def identity(root=ROOT):
    return instance_id(root, Path(os.environ.get('BOOKKEEPING_DATA_DIR', root/'data')), Path(os.environ.get('BOOKKEEPING_IMAGES_DIR', root/'images')))


def matching_service(port, expected):
    try:
        with DIRECT_HTTP.open(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
            body = json.loads(response.read(4096))
            return isinstance(body, dict) and body.get('status') == 'ok' and body.get('project') == 'stitch-ledger' and body.get('instance') == expected
    except (OSError, ValueError, URLError):
        return False


def free_port(port):
    # Check all IPv4 interfaces, matching Uvicorn's 0.0.0.0 listener.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('0.0.0.0', port))
        return True
    except OSError:
        return False


def choose_port(preferred, expected, previous=None):
    candidates = list(range(preferred, min(65535, preferred+19)+1))
    for port in dict.fromkeys([preferred, previous, *candidates]):
        if isinstance(port, int) and 1 <= port <= 65535 and matching_service(port, expected):
            return port, True
    for port in candidates:
        if free_port(port):
            return port, False
    raise RuntimeError('没有可用端口。请用 --port 8080 指定另一个起始端口。')


def source_digest(root=ROOT):
    paths = [root/'frontend/index.html', root/'frontend/package.json', root/'frontend/package-lock.json', root/'frontend/vite.config.js']
    for folder in ('src', 'public'):
        paths.extend(p for p in (root/'frontend'/folder).rglob('*') if p.is_file())
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest(), max(p.stat().st_mtime for p in paths)


def node_info(binary):
    try:
        result = subprocess.run([str(binary), '-p', 'JSON.stringify({version:process.versions.node,arch:process.arch,platform:process.platform})'], capture_output=True, text=True, timeout=5)
        return json.loads(result.stdout) if result.returncode == 0 else {}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}


def compatible_node(info, architecture):
    try:
        major, minor, patch = (int(v) for v in info['version'].split('.'))
        supported = (major == 20 and (minor, patch) >= (19, 0)) or (major, minor, patch) >= (22, 12, 0)
        return supported and info.get('arch') == {'x86_64':'x64','arm64':'arm64'}[architecture] and info.get('platform') == 'darwin'
    except (KeyError, ValueError):
        return False


def verify_sha256(path, expected):
    with path.open('rb') as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    if len(expected) != 64 or digest.hexdigest() != expected:
        raise RuntimeError('Node.js 下载校验失败，请再次双击重试。')


def extract_node(archive_path, destination):
    with tarfile.open(archive_path) as archive:
        # Python 3.12's data filter keeps extraction within the runtime directory.
        if hasattr(tarfile, 'data_filter'):
            archive.extractall(destination, filter='data')
        else:
            for member in archive.getmembers():
                target = (destination/member.name).resolve()
                if destination.resolve() not in target.parents or not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                    raise RuntimeError('Node.js 安装包内容无效。')
                if member.issym() or member.islnk():
                    linked = ((target.parent/member.linkname) if member.issym() else destination/member.linkname).resolve()
                    if destination.resolve() not in linked.parents:
                        raise RuntimeError('Node.js 安装包链接无效。')
            archive.extractall(destination)


def download_node(runtime, architecture):
    if int(platform.mac_ver()[0].split('.')[0]) < 11:
        raise RuntimeError('当前系统低于 macOS 11，无法自动构建新版前端。请从已有电脑复制 frontend/dist，再双击启动。')
    arch = {'x86_64':'x64', 'arm64':'arm64'}[architecture]
    name = f'node-v{NODE_VERSION}-darwin-{arch}'
    binary = runtime/name/'bin/node'
    if compatible_node(node_info(binary), architecture):
        return binary
    print('下载项目专用 Node.js（不会修改系统环境）…', flush=True)
    downloads = runtime/'downloads'
    downloads.mkdir(parents=True, exist_ok=True)
    archive_path = downloads/(name+'.tar.gz')
    checksum_path = downloads/'node-checksums.txt'
    base = f'https://nodejs.org/dist/v{NODE_VERSION}'
    curl = ['/usr/bin/curl','-fL','--retry','2','--connect-timeout','20','--max-time','300']
    subprocess.run([*curl, base+'/'+name+'.tar.gz', '-o', str(archive_path)+'.part'], check=True)
    subprocess.run([*curl, base+'/SHASUMS256.txt', '-o', str(checksum_path)], check=True)
    expected = next((line.split()[0] for line in checksum_path.read_text().splitlines() if line.split()[-1] == name+'.tar.gz'), '')
    verify_sha256(Path(str(archive_path)+'.part'), expected)
    Path(str(archive_path)+'.part').replace(archive_path)
    with tempfile.TemporaryDirectory(prefix='node-stage-', dir=runtime) as stage:
        stage = Path(stage)
        extract_node(archive_path, stage)
        target = runtime/name
        if target.exists():
            target.rename(runtime/(name+'-old-'+str(time.time_ns())))
        (stage/name).rename(target)
    if not compatible_node(node_info(binary), architecture):
        raise RuntimeError('下载的 Node.js 不能在当前电脑运行，请检查系统版本。')
    return binary


def ensure_frontend(root, runtime, architecture, rebuild=False):
    digest, modified = source_digest(root)
    index = root/'frontend/dist/index.html'
    manifest = root/'frontend/dist/.bookkeeping-build.json'
    if not rebuild and index.is_file():
        recorded = read_json(manifest)
        if recorded.get('source') == digest or (not recorded and index.stat().st_mtime >= modified):
            write_json(manifest, {'source': digest})
            print('前端页面已就绪。', flush=True)
            return
    candidates = [Path(p) for p in (shutil.which('node'), '/usr/local/bin/node', '/opt/homebrew/bin/node') if p]
    node = next((p for p in candidates if compatible_node(node_info(p), architecture)), None)
    if node is None:
        node = download_node(runtime, architecture)
    npm = node.parent/'npm'
    if not npm.exists():
        raise RuntimeError('Node.js 缺少 npm，请重新安装 Node.js 或移除项目专用 Node 目录后重试。')
    env = dict(os.environ, PATH=str(node.parent)+os.pathsep+os.environ.get('PATH',''), npm_config_cache=str(runtime/'npm-cache'), npm_config_update_notifier='false')
    stamp = runtime/'frontend-environment.json'
    expected = {'lock': hashlib.sha256((root/'frontend/package-lock.json').read_bytes()).hexdigest(), **node_info(node), 'root':str(root)}
    if read_json(stamp) != expected or not (root/'frontend/node_modules/.package-lock.json').is_file():
        print('安装适合本机芯片的前端依赖…', flush=True)
        subprocess.run([str(npm),'ci','--no-audit','--no-fund'], cwd=root/'frontend', env=env, check=True)
        write_json(stamp, expected)
    print('正在构建手机页面…', flush=True)
    subprocess.run([str(npm),'run','build'], cwd=root/'frontend', env=env, check=True)
    write_json(manifest, {'source':digest})


@contextmanager
def launch_lock(runtime):
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime/'launch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield
        fcntl.flock(lock, fcntl.LOCK_UN)


def browser_open(url):
    subprocess.Popen(['/usr/bin/open', url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def show_addresses(port):
    address = local_ip()
    print(f'\n电脑访问：http://127.0.0.1:{port}', flush=True)
    print(f'手机访问：http://{address}:{port}  （手机和电脑连接同一个 Wi-Fi）', flush=True)


def serve(port, expected, runtime):
    path = runtime/f'server-{port}.log'
    with path.open('a') as log:
        child = subprocess.Popen([sys.executable, str(ROOT/'run.py'),'--port',str(port)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic()+30
        while time.monotonic()<deadline:
            if child.poll() is not None:
                break
            if matching_service(port, expected):
                return child
            time.sleep(.2)
        raise RuntimeError('服务没有成功启动。日志末尾：\n'+path.read_text()[-2500:])
    except BaseException:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=10)
        raise


def main():
    parser = argparse.ArgumentParser(description='针线小账 · macOS 一键启动')
    parser.add_argument('--port', type=int, default=int(os.environ.get('BOOKKEEPING_PORT',8000)))
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--rebuild', action='store_true')
    parser.add_argument('--prepare-only', action='store_true', help='只准备运行环境，不启动服务')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('端口应在 1 到 65535 之间。')
    architecture = platform.machine()
    runtime = ROOT/'.runtime'
    expected = identity()
    child = None
    try:
        with launch_lock(runtime):
            previous = read_json(runtime/'last-server.json').get('port')
            port, reuse = choose_port(args.port, expected, previous)
            if reuse and not args.prepare_only:
                if args.rebuild:
                    ensure_frontend(ROOT, runtime/architecture, architecture, rebuild=True)
                write_json(runtime/'last-server.json', {'port':port,'instance':expected})
                print('这份账本的服务已在运行。', flush=True)
                show_addresses(port)
                if not args.no_browser:
                    browser_open(f'http://127.0.0.1:{port}')
                return 0
            ensure_frontend(ROOT, runtime/architecture, architecture, args.rebuild)
            if args.prepare_only:
                print('运行环境和前端页面已准备完成。', flush=True)
                return 0
            if port != args.port:
                print(f'{args.port} 端口被占用，本次使用 {port}。', flush=True)
            child = serve(port, expected, runtime)
            write_json(runtime/'last-server.json', {'port':port,'pid':child.pid,'instance':expected})
        show_addresses(port)
        print('\n服务已启动。请保留这个终端窗口；按 Ctrl+C 停止服务。', flush=True)
        print(f'运行日志：{runtime / ("server-"+str(port)+".log")}', flush=True)
        if not args.no_browser:
            browser_open(f'http://127.0.0.1:{port}')
        return child.wait()
    except KeyboardInterrupt:
        print('\n正在停止服务…', flush=True)
        return 0
    finally:
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print('\n启动失败：'+str(error), file=sys.stderr, flush=True)
        sys.exit(1)
