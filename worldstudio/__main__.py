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


def direct_route_demo(project):
    """Create a new macro edge by repurposing the existing W102-to-tower bone.

    Retains its waypoints/indices but redirects the final segment to W103. This
    changes the path graph itself rather than chaining two old macro paths.
    In-game traversal and fresh-save unlocks remain separate integration tests.
    """
    chain_demo(project)
    project.bone_renames = [{'model': project.path_model,
        'old': 'RW102W1T0', 'new': 'RW102W103'}]
    for row in project.points.rows:
        if row[1] == 'W102':
            row[4] = 'RW102W103'
    matches = [r for r in project.routes.rows if r[0] == 'RK02hW1T0']
    if len(matches) != 1:
        raise ValueError('Expected original final tower segment RK02hW1T0')
    matches[0][0] = 'RK02hW103'
    matches[0][1] = '坂'  # Existing slope movement type; destination rises to W103.
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
    demo.add_argument('--island', type=Path, help='Experimental original OBJ replacement of one existing rigid grass mesh')
    demo.add_argument('--direct-route', action='store_true', help='Experimental new W102-W103 macro edge, bypassing the tower endpoint')
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
            p = (direct_route_demo if args.direct_route else chain_demo)(WorldProject.open(args.source))
            if args.island:
                from .editor import read_obj
                vertices, faces = read_obj(args.island)
                p.geometry = {'vertices': vertices, 'faces': faces}
                p.terrain = str(args.island.resolve())
            if args.out.exists():
                raise FileExistsError('Choose a new output folder')
            p.save(args.out / 'three-level-chain.nws.json')
            manifest = p.export(args.out / 'content/Common/course_select/CS_W1.szs')
            notes = [
                'Experimental resource patch. Not yet verified in-game.',
                'Normal progression: W101 -> W102 -> W103; all other points remain.',
                ('New macro edge RW102W103; final segment RK02hW103 uses existing waypoints.'
                 if args.direct_route else 'W102 uses existing RW102W1T0,RW1T0W103 macro paths.'),
                ('One rigid grass shape replaced by original OBJ; other shapes retained.'
                 if args.island else 'No mesh replacement selected.'),
                'Level files, cameras, scripts and saves unchanged.',
                'Test on a separate game copy/profile. Contains user-owned resources; do not redistribute.']
            (args.out / 'EXPERIMENT.txt').write_text('\n'.join(notes) + '\n', encoding='utf-8')
            print(json.dumps(manifest, indent=2))
        elif args.command == 'export':
            print(json.dumps(WorldProject.load(args.project).export(args.out), indent=2))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
