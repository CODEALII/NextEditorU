"""Run the separate GPL Cobra checkout safely, without importing/copying its code.

All output goes into a new directory outside source directories and the game
dump. The bridge never installs a script loader or deploys WMSC to the game.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys


ROOT=Path(__file__).resolve().parents[1]
DEFAULT_COBRA=ROOT/'external/Cobra'


def sha256(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()


def validate_wmsc(data):
    """Independently validate the NSMBU v1.3 sparse big-endian WMSC format."""
    if len(data)<16 or data[:8]!=b'WMS0U130':
        raise ValueError('Expected NSMBU v1.3 WMS0U130 header')
    size,count=struct.unpack_from('>II',data,8)
    if size!=len(data) or count>65535 or 16+12*count>size:
        raise ValueError('Invalid WMSC length or table count')
    ids=list(struct.unpack_from('>'+str(count)+'I',data,16))
    if ids!=sorted(set(ids)):
        raise ValueError('WMSC script IDs must be sorted and unique')
    table=16+4*count
    starts=[];priorities=[]
    for i in range(count):
        priority,start=struct.unpack_from('>II',data,table+8*i)
        if start<16+12*count or start>size-8 or (start-(16+12*count))%8!=0:
            raise ValueError('Invalid WMSC command offset')
        priorities.append(priority);starts.append(start)
    if starts!=sorted(set(starts)):
        raise ValueError('WMSC scripts must occupy separate ordered command ranges')
    command_counts=[]
    for start,end in zip(starts,starts[1:]+[size]):
        if end<=start or (end-start)%8:
            raise ValueError('Invalid WMSC command range')
        commands=[struct.unpack_from('>II',data,p) for p in range(start,end,8)]
        if commands[-1][0]!=344 or any(command==344 for command,_ in commands[:-1]):
            raise ValueError('WMSC script must end with the v1.3 terminator 344')
        command_counts.append(len(commands))
    return {'format':'WMS0U130','size':size,'script_count':count,'script_ids':ids,
            'priorities':priorities,'command_counts':command_counts,
            'sha256':hashlib.sha256(data).hexdigest(),'game_verified':False}


def upstream_commit(cobra_root):
    proc=subprocess.run(['git','-C',str(cobra_root),'rev-parse','HEAD'],
                        capture_output=True,text=True,check=False)
    commit=proc.stdout.strip()
    if proc.returncode or len(commit)!=40 or any(c not in '0123456789abcdef' for c in commit):
        raise ValueError('Cobra must be a Git checkout so provenance can be recorded')
    return commit


def local_diff(cobra_root):
    proc=subprocess.run(['git','-C',str(cobra_root),'diff','--binary','--no-ext-diff','HEAD','--'],
                        capture_output=True,check=False)
    if proc.returncode:
        raise ValueError('Unable to record Cobra tracked working-tree patch')
    return proc.stdout


def run_bridge(operation,inputs,output,cobra_root=DEFAULT_COBRA,timeout=120):
    if operation not in ('analyze','export','encode'):
        raise ValueError('Unsupported Cobra operation')
    inputs=[Path(p).resolve(strict=True) for p in inputs]
    expected=2 if operation=='encode' else 1
    if len(inputs)!=expected or any(not p.is_file() for p in inputs):
        raise ValueError(f'{operation} requires {expected} input file(s)')
    cobra_root=Path(cobra_root).resolve(strict=True)
    script=cobra_root/'cobra.py'
    if not script.is_file():
        raise ValueError('Cobra checkout missing cobra.py')
    output=Path(output).resolve()
    if output.exists():
        raise FileExistsError(f'Output directory already exists: {output}')
    protected=(ROOT/'NSMBU Modding Project').resolve()
    if output.is_relative_to(protected) or output.is_relative_to(cobra_root) or any(output.is_relative_to(p.parent) for p in inputs):
        raise ValueError('Output must be outside the game dump, Cobra checkout and input directories')
    commit=upstream_commit(cobra_root)
    diff=local_diff(cobra_root)
    source_info=[{'path':str(p),'sha256':sha256(p),'size':p.stat().st_size} for p in inputs]
    output.mkdir(parents=True,exist_ok=False)
    if diff:
        with (output/'cobra-local.patch').open('xb') as stream:stream.write(diff)
    command=[sys.executable,str(script),operation,*map(str,inputs)]
    if operation=='export':command.extend([str(output/'scripts.txt'),str(output/'version.json')])
    elif operation=='encode':command.append(str(output/'scripts.wmsc'))
    metadata={'operation':operation,'cobra_url':'https://github.com/RoadrunnerWMC/Cobra',
              'cobra_commit':commit,'cwd':str(cobra_root),'command':command,
              'cobra_dirty':bool(diff),'cobra_diff_sha256':hashlib.sha256(diff).hexdigest(),
              'cobra_python_sha256':{p.name:sha256(p) for p in sorted(cobra_root.glob('*.py'))},
              'inputs':source_info,'success':False,'deployed':False}
    try:
        proc=subprocess.run(command,cwd=cobra_root,capture_output=True,text=True,
                            encoding='utf-8',errors='replace',timeout=timeout,check=False)
        (output/'stdout.log').write_text(proc.stdout,encoding='utf-8')
        (output/'stderr.log').write_text(proc.stderr,encoding='utf-8')
        metadata['returncode']=proc.returncode
        if proc.returncode:
            raise RuntimeError(f'Cobra {operation} failed; see {output / "stderr.log"}')
        if operation=='export':
            if not (output/'scripts.txt').is_file() or not (output/'version.json').is_file():
                raise ValueError('Cobra export did not produce both expected files')
            metadata['analysis']=json.loads((output/'version.json').read_text(encoding='utf-8'))
        elif operation=='encode':
            metadata['wmsc']=validate_wmsc((output/'scripts.wmsc').read_bytes())
        if any(sha256(p)!=info['sha256'] for p,info in zip(inputs,source_info)):
            raise RuntimeError('Source file changed during Cobra invocation')
        metadata['outputs']={p.name:{'sha256':sha256(p),'size':p.stat().st_size}
                             for p in output.iterdir() if p.is_file()}
        metadata['success']=True
    except Exception as exc:
        metadata['error']=str(exc)
        raise
    finally:
        with (output/'provenance.json').open('x',encoding='utf-8') as stream:
            json.dump(metadata,stream,indent=2)
    return metadata


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['analyze','export','encode'])
    parser.add_argument('inputs',nargs='+',type=Path)
    parser.add_argument('--output',required=True,type=Path,help='New output directory; existing directories are refused')
    parser.add_argument('--cobra-root',type=Path,default=DEFAULT_COBRA)
    args=parser.parse_args()
    result=run_bridge(args.operation,args.inputs,args.output,args.cobra_root)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
