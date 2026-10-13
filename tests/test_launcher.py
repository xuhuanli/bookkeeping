import hashlib
import io
import json
from pathlib import Path
import tarfile

import pytest

from backend.identity import instance_id
from scripts import launcher


@pytest.mark.parametrize('version,arch,ok', [('20.18.3','x64',False),('20.19.0','x64',True),('21.9.0','x64',False),('22.11.0','x64',False),('22.12.0','x64',True),('24.0.0','x64',True),('22.23.0','arm64',False)])
def test_intel_node_compatibility(version,arch,ok):
    assert launcher.compatible_node({'version':version,'arch':arch,'platform':'darwin'},'x86_64') is ok


def test_reuses_only_the_same_ledger_and_skips_occupied_port(monkeypatch):
    monkeypatch.setattr(launcher,'matching_service',lambda port,expected:port==8001 and expected=='this-ledger')
    monkeypatch.setattr(launcher,'free_port',lambda port:port>=8002)
    assert launcher.choose_port(8000,'this-ledger',8001)==(8001,True)
    assert launcher.choose_port(8000,'another-ledger',8001)==(8002,False)
    assert launcher.choose_port(65535,'another-ledger')==(65535,False)


def test_instance_identity_changes_with_ledger_storage(tmp_path):
    assert instance_id(tmp_path,tmp_path/'data',tmp_path/'images') != instance_id(tmp_path,tmp_path/'other-data',tmp_path/'images')


def frontend_fixture(root):
    for name in ['index.html','package.json','package-lock.json','vite.config.js','src/App.vue','public/mark.svg']:
        path=root/'frontend'/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('fixture '+name)


def test_prebuilt_frontend_needs_no_node_and_tracks_source_edits(tmp_path,monkeypatch):
    root=tmp_path/'项目 with spaces';frontend_fixture(root)
    index=root/'frontend/dist/index.html';index.parent.mkdir(parents=True);index.write_text('built page')
    digest,_=launcher.source_digest(root)
    launcher.write_json(index.parent/'.bookkeeping-build.json',{'source':digest})
    monkeypatch.setattr(launcher,'download_node',lambda *args:pytest.fail('A matching static build must not download Node'))
    launcher.ensure_frontend(root,tmp_path/'runtime','x86_64')
    (root/'frontend/src/App.vue').write_text('changed component')
    assert launcher.source_digest(root)[0]!=digest


def test_arm_dependencies_are_reinstalled_before_an_intel_build(tmp_path,monkeypatch):
    root=tmp_path/'项目 with spaces';frontend_fixture(root)
    node=tmp_path/'bin/node';node.parent.mkdir();node.touch();(node.parent/'npm').touch()
    runtime=tmp_path/'runtime';runtime.mkdir()
    launcher.write_json(runtime/'frontend-environment.json',{'arch':'arm64'})
    monkeypatch.setattr(launcher.shutil,'which',lambda name:str(node))
    monkeypatch.setattr(launcher,'node_info',lambda path:{'version':'22.23.0','arch':'x64','platform':'darwin'})
    commands=[]
    monkeypatch.setattr(launcher.subprocess,'run',lambda args,**kwargs:commands.append((args,kwargs)))
    launcher.ensure_frontend(root,runtime,'x86_64')
    assert commands[0][0][1]=='ci'
    assert commands[1][0][1:]==['run','build']
    assert commands[0][1]['cwd']==root/'frontend'
    assert commands[0][1]['env']['PATH'].startswith(str(node.parent))


def test_download_checksum_and_archive_paths(tmp_path):
    payload=tmp_path/'node.tar.gz';payload.write_bytes(b'download')
    launcher.verify_sha256(payload,hashlib.sha256(b'download').hexdigest())
    with pytest.raises(RuntimeError):launcher.verify_sha256(payload,'0'*64)
    archive=tmp_path/'unsafe.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        member=tarfile.TarInfo('../../outside.txt');member.size=4
        tar.addfile(member,io.BytesIO(b'bad!'))
    destination=tmp_path/'stage';destination.mkdir()
    with pytest.raises((tarfile.TarError,RuntimeError)):
        launcher.extract_node(archive,destination)
    assert not (tmp_path.parent/'outside.txt').exists()


def test_discovers_existing_server_if_saved_port_is_stale(monkeypatch):
    monkeypatch.setattr(launcher,'matching_service',lambda port,expected:port==8003)
    monkeypatch.setattr(launcher,'free_port',lambda port:port==8001)
    assert launcher.choose_port(8000,'this-ledger',8080)==(8003,True)


def test_unrelated_health_json_and_bad_cache_are_ignored(tmp_path,monkeypatch):
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,limit):return b'[]'
    monkeypatch.setattr(launcher.DIRECT_HTTP,'open',lambda *args,**kwargs:Response())
    assert not launcher.matching_service(8000,'this-ledger')
    metadata=tmp_path/'metadata.json';metadata.write_text('[]')
    assert launcher.read_json(metadata)=={}
