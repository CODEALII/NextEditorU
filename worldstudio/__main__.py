import argparse
import json
from pathlib import Path
from .project import WorldProject


DEFAULT_SOURCE = Path(__file__).resolve().parents[1] / 'NSMBU Modding Project/content/Common/course_select/CS_W1.szs'


def chain_demo(project):
    """Experimental three-level normal progression using existing route bones.

    Preserve every row/index and secret-island reference. The tower's point
    remains present for scripts. This is not a new island or runtime proof.
    """
    if project.point_name != 'pointW1.csv':
        raise ValueError('This recipe is only defined for World 1')
    by_name = {r[1]: r for r in project.points.rows}
    for required in ('RW101W102', 'RW102W1T0', 'RW1T0W103'):
        project.skeletons.unique(required)
    a, b, c = (by_name[n] for n in ('W101', 'W102', 'W103'))
    a[3:8] = ['W102', 'RW101W102', a[5], '', '']
    b[3:8] = ['W103', 'RW102W1T0,RW1T0W103', b[5], '', '']
    c[3:8] = ['', '', c[5], '', '']
    return project


def main():
    parser = argparse.ArgumentParser(prog='python -m worldstudio')
    sub = parser.add_subparsers(dest='command')
    gui = sub.add_parser('gui', help='Open the standalone visual editor')
    gui.add_argument('source', nargs='?', default=str(DEFAULT_SOURCE))
    inspect = sub.add_parser('inspect', help='Read archive and report graph/bones')
    inspect.add_argument('source', nargs='?', default=str(DEFAULT_SOURCE))
    demo = sub.add_parser('demo', help='Build experimental three-level progression patch')
    demo.add_argument('--source', default=str(DEFAULT_SOURCE))
    demo.add_argument('--out', required=True, type=Path)
    exp = sub.add_parser('export', help='Validate and export a saved project')
    exp.add_argument('project')
    exp.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command in (None, 'gui'):
            from .editor import main as editor_main
            editor_main([args.source] if args.command else [])
        elif args.command == 'inspect':
            p = WorldProject.open(args.source)
            print(json.dumps({'source': str(p.source), 'sha256': p.source_sha256,
                'points': len(p.points.rows), 'segments': len(p.routes.rows),
                'models': {k: len(v) for k,v in p.skeletons.models.items()},
                'positions': p.positions, 'validation_errors': p.validate()}, indent=2))
        elif args.command == 'demo':
            p = chain_demo(WorldProject.open(args.source))
            if args.out.exists():
                raise FileExistsError('Choose a new output folder')
            p.save(args.out / 'three-level-chain.nws.json')
            manifest = p.export(args.out / 'content/Common/course_select/CS_W1.szs')
            (args.out / 'EXPERIMENT.txt').write_text(
                'Experimental resource patch. Not yet verified in-game.\n'
                'Normal progression: W101 -> W102 -> W103; all other points remain.\n'
                'W102 uses existing RW102W1T0,RW1T0W103 macro paths.\n'
                'Original model, level files, cameras, scripts and saves unchanged.\n'
                'Test on a separate game copy/profile. Contains user-owned resources; do not redistribute.\n', encoding='utf-8')
            print(json.dumps(manifest, indent=2))
        elif args.command == 'export':
            print(json.dumps(WorldProject.load(args.project).export(args.out), indent=2))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
