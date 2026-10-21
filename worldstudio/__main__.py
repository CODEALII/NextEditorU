import argparse
import json
import re
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


def _validate_with_graph_profile(project, profile_path):
    """Validate a project against explicitly selected entry/required nodes."""
    from .graph_validation import load_native_graph_profile, validate_native_world

    world = re.search(r'pointW([1-9])', project.point_name)
    if not world:
        raise ValueError('Cannot match graph profile to the source world')
    world_prefix = f'W{world[1]}'
    profile = load_native_graph_profile(profile_path, world_prefix)
    references = set(project.references)
    for rename in project.bone_renames:
        references.discard(rename.get('old'))
        if rename.get('new'):
            references.add(rename['new'])
    issues = set(project.validate())
    issues.update(validate_native_world(
        project.points.rows, project.routes.rows, known_references=references,
        initial_points=project.points.initial, initial_routes=project.routes.initial,
        world_prefix=world_prefix,
        entry_points=profile['entry_points'],
        required_locations=profile['required_locations']))
    return sorted(issues)


def _shader_summary(report, limit=24):
    """Format bounded, readable interface metadata for terminal inspection."""
    lines = [
        f"SHARCFB v{report['version']} - {report['archive_name']} - {report['endian']} endian",
        f"{report['shader_binary_count']} shader binaries - {report['shader_program_count']} programs - metadata only",
    ]

    def names(items, format_item):
        rendered = [format_item(item)[:180] for item in items[:limit]]
        if len(items) > limit:
            rendered.append(f"... {len(items) - limit} more")
        return ", ".join(rendered) if rendered else "(none)"

    def variation(item):
        values = item['values']
        shown = "|".join(value[:32] for value in values[:8])
        if len(values) > 8:
            shown += f"|...+{len(values) - 8}"
        return f"{item['name']}={{{shown}}}"

    stage_labels = {0: "vertex", 1: "pixel", 2: "geometry"}
    for program in report['programs']:
        stages = ", ".join(stage_labels[index] for index in range(3)
                            if program['shader_flags'] & (1 << index))
        lines.extend((
            "",
            f"{program['name']} - {stages} - {program['variation_count']} compiled combinations",
            "  variations: " + names(program['variation_macros'], variation),
            "  samplers: " + names(program['samplers'], lambda item:
                f"{item['symbol']}={item['name']}"),
            "  uniforms: " + names(program['uniforms'], lambda item: item['name']),
            "  uniform blocks: " + names(program['uniform_blocks'], lambda item: item['name']),
            "  attributes: " + names(program['attributes'], lambda item:
                f"{item['symbol']}={item['name']}"),
        ))
    lines.extend(("", "GX2 instructions, active variation, and rendered material behavior are not evaluated."))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(prog='python -m worldstudio')
    sub = parser.add_subparsers(dest='command')
    gui = sub.add_parser('gui', help='Open the standalone visual editor')
    gui.add_argument('source', nargs='?', default=str(DEFAULT_SOURCE))
    inspect = sub.add_parser('inspect', help='Read archive and report graph/bones')
    inspect.add_argument('source', nargs='?', default=str(DEFAULT_SOURCE))
    graph = sub.add_parser('validate-graph', help='Validate native references and optional directed reachability')
    graph.add_argument('source', nargs='?', default=str(DEFAULT_SOURCE),
                       help='World .szs archive or saved .nws.json project')
    graph.add_argument('--entry', action='append', default=[], metavar='POINT',
                       help='Playable entry point; repeat to specify multiple starts')
    graph.add_argument('--require', action='append', default=[], metavar='POINT',
                       help='Location that must be reachable from an entry; repeat as needed')
    graph.add_argument('--profile', type=Path,
                       help='Versioned JSON file with explicit world entry and required points')
    shaders = sub.add_parser('inspect-shaders', help='Read SHARCFB shader interface metadata')
    shaders.add_argument('source', type=Path,
                         help='SHARCFB file or SZS/SARC containing a SHARCFB entry')
    shaders.add_argument('--entry', help='SHARCFB member name inside an SZS/SARC archive')
    shaders.add_argument('--program', help='Return only the named shader program')
    shaders.add_argument('--json', action='store_true', help='Print the full metadata object as JSON')
    demo = sub.add_parser('demo', help='Build experimental three-level progression patch')
    demo.add_argument('--source', default=str(DEFAULT_SOURCE))
    demo.add_argument('--out', required=True, type=Path)
    demo.add_argument('--island', type=Path, help='Experimental OBJ top-surface patch projected onto an existing rigid grass mesh')
    demo.add_argument('--direct-route', action='store_true', help='Experimental new W102-W103 macro edge, bypassing the tower endpoint')
    exp = sub.add_parser('export', help='Validate and export a saved project')
    exp.add_argument('project')
    exp.add_argument('--out', type=Path, required=True)
    exp.add_argument('--profile', type=Path,
                     help='Require directed reachability for a versioned graph profile before exporting')
    verify = sub.add_parser('verify-export', help='Reimport an export and compare it with the saved project')
    verify.add_argument('project', help='Saved World Studio JSON project')
    verify.add_argument('archive', type=Path, help='Exported world archive produced with its manifest')
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
        elif args.command == 'validate-graph':
            p = (WorldProject.load(args.source) if str(args.source).lower().endswith('.json')
                 else WorldProject.open(args.source))
            from .graph_validation import load_native_graph_profile, validate_native_world
            references = set(p.references)
            for rename in p.bone_renames:
                references.discard(rename.get('old'))
                if rename.get('new'):
                    references.add(rename['new'])
            world = re.search(r'pointW([1-9])', p.point_name)
            world_prefix = f'W{world[1]}' if world else None
            entry_points, required_locations = args.entry, args.require
            if args.profile:
                if args.entry or args.require:
                    raise ValueError('Use either --profile or --entry/--require, not both')
                if not world_prefix:
                    raise ValueError('Cannot match graph profile to the source world')
                profile = load_native_graph_profile(args.profile, world_prefix)
                entry_points = list(profile['entry_points'])
                required_locations = list(profile['required_locations'])
            issues = set(p.validate())
            issues.update(validate_native_world(
                p.points.rows, p.routes.rows, known_references=references,
                initial_points=p.points.initial, initial_routes=p.routes.initial,
                world_prefix=world_prefix,
                entry_points=entry_points, required_locations=required_locations))
            report = {'source': str(p.source),
                      'profile': str(args.profile) if args.profile else None,
                      'entry_points': entry_points,
                      'required_locations': required_locations,
                      'reachable_locations_checked': bool(required_locations),
                      'validation_errors': sorted(issues)}
            print(json.dumps(report, indent=2))
            if issues:
                parser.exit(1, 'Graph validation failed.\n')
        elif args.command == 'inspect-shaders':
            from .archive import Archive
            from .shader_archive import parse_sharcfb
            raw = args.source.read_bytes()
            if raw[:4] in (b'Yaz0', b'SARC'):
                archive = Archive(raw)
                candidates = [name for name in archive.entries
                              if name.lower().endswith('.sharcfb')]
                if args.entry:
                    if args.entry not in candidates:
                        raise ValueError(f'No SHARCFB entry named {args.entry!r}')
                    shader_data = archive.read(args.entry)
                elif len(candidates) == 1:
                    shader_data = archive.read(candidates[0])
                elif candidates:
                    raise ValueError('Choose --entry from: ' + ', '.join(candidates))
                else:
                    raise ValueError('Archive contains no SHARCFB entries')
            else:
                if args.entry:
                    raise ValueError('--entry is only valid for an SZS/SARC source')
                shader_data = raw
            report = parse_sharcfb(shader_data)
            if args.program:
                selected = [program for program in report['programs']
                            if program['name'] == args.program]
                if not selected:
                    raise ValueError(f"Shader program not found: {args.program}")
                report['programs'] = selected
            print(json.dumps(report, indent=2) if args.json else _shader_summary(report))
        elif args.command == 'demo':
            p = (direct_route_demo if args.direct_route else chain_demo)(WorldProject.open(args.source))
            obj_compatibility_warnings = ()
            if args.island:
                from .editor import read_obj
                (vertices, faces), obj_compatibility_warnings = read_obj(
                    args.island, include_report=True)
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
                ('Original OBJ surface projected onto the existing grass topology and UVs; '
                 'terrain appearance and collision remain unverified.'
                 if args.island else 'No terrain patch selected.'),
                *[f'OBJ compatibility: {warning}.' for warning in obj_compatibility_warnings],
                'Level files, cameras, scripts and saves unchanged.',
                'Test on a separate game copy/profile. Contains user-owned resources; do not redistribute.']
            (args.out / 'EXPERIMENT.txt').write_text('\n'.join(notes) + '\n', encoding='utf-8')
            print(json.dumps(manifest, indent=2))
        elif args.command == 'export':
            project = WorldProject.load(args.project)
            if args.profile:
                issues = _validate_with_graph_profile(project, args.profile)
                if issues:
                    raise ValueError('Graph validation failed:\n' + '\n'.join(issues))
            print(json.dumps(project.export(args.out), indent=2))
        elif args.command == 'verify-export':
            from .export_verify import verify_export
            report = verify_export(WorldProject.load(args.project), args.archive)
            print(json.dumps(report, indent=2))
            if not report['verified']:
                parser.exit(1, 'Export verification failed.\n')
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
