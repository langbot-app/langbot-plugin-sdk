from __future__ import annotations

import io
import zipfile

from langbot_plugin.box.skill_store import BoxSkillStore


def _skill_zip(name: str = 'demo') -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        zf.writestr(
            f'{name}/SKILL.md',
            '---\n'
            f'name: {name}\n'
            f'display_name: {name.title()}\n'
            'description: Demo skill\n'
            '---\n\n'
            'Use this skill for tests.\n',
        )
        zf.writestr(f'{name}/notes.txt', 'hello')
    return buffer.getvalue()


def _nested_skill_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        zf.writestr(
            'repo/packages/alpha/SKILL.md',
            '---\nname: alpha\ndisplay_name: Alpha\n---\n\nAlpha instructions.\n',
        )
        zf.writestr(
            'repo/packages/beta/SKILL.md',
            '---\nname: beta\ndisplay_name: Beta\n---\n\nBeta instructions.\n',
        )
    return buffer.getvalue()


def test_skill_store_installs_zip_under_configured_relative_skills_root(tmp_path):
    store = BoxSkillStore({
        'local': {
            'host_root': str(tmp_path),
            'skills_root': 'custom-skills',
        }
    })

    preview = store.preview_zip_upload(file_bytes=_skill_zip(), filename='demo.zip')
    assert preview[0]['package_root'] == str(tmp_path / 'custom-skills' / 'demo-upload')

    installed = store.install_zip_upload(file_bytes=_skill_zip(), filename='demo.zip')
    assert installed[0]['name'] == 'demo'
    assert installed[0]['package_root'] == str(tmp_path / 'custom-skills' / 'demo-upload')

    files = store.list_skill_files('demo')
    assert {entry['name'] for entry in files['entries']} == {'SKILL.md', 'notes.txt'}

    content = store.read_skill_file('demo', 'notes.txt')
    assert content['content'] == 'hello'

    store.write_skill_file('demo', 'notes.txt', 'updated')
    assert store.read_skill_file('demo', 'notes.txt')['content'] == 'updated'


def test_skill_store_supports_source_subdir_before_selecting_candidates(tmp_path):
    store = BoxSkillStore({
        'local': {
            'host_root': str(tmp_path),
            'skills_root': 'skills',
        }
    })

    preview = store.preview_zip_upload(
        file_bytes=_nested_skill_zip(),
        filename='repo.zip',
        source_subdir='packages',
    )

    assert [skill['source_path'] for skill in preview] == ['alpha', 'beta']

    installed = store.install_zip_upload(
        file_bytes=_nested_skill_zip(),
        filename='repo.zip',
        source_subdir='packages',
        source_paths=['beta'],
    )

    assert [skill['name'] for skill in installed] == ['beta']
    assert installed[0]['package_root'] == str(tmp_path / 'skills' / 'repo-beta-upload')
