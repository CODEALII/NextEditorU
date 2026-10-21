import hashlib
from pathlib import Path
import random
import struct
import unittest

from worldstudio.archive import Archive
from worldstudio.bfres import Skeletons
from worldstudio.bfres_names import build_trie,dictionary_lookup,rename_bone
from tests.test_mesh import fixture


def valid_fixture():
    data=bytearray(fixture())
    for i,node in enumerate(build_trie(['root'])):
        struct.pack_into('>IHH',data,0x188+16*i,*node)
    return bytes(data)


class TrieTests(unittest.TestCase):
    def test_prefixes_branches_and_shuffled_order(self):
        names=['A','AB','ABC','a','RW102W103','RW102W1T0']+[f'W{i:03d}' for i in range(150)]
        random.Random(1234).shuffle(names)
        data=bytearray(12000);dictionary=16
        struct.pack_into('>II',data,dictionary,8+16*(len(names)+1),len(names))
        text_start=3000
        for i,node in enumerate(build_trie(names)):
            p=dictionary+8+16*i
            struct.pack_into('>IHH',data,p,*node)
            if i:
                text=names[i-1].encode()+b'\0'
                data[text_start:text_start+len(text)]=text
                struct.pack_into('>I',data,p+8,text_start-(p+8))
                struct.pack_into('>I',data,p+12,11000+i-(p+12))
                text_start+=len(text)
        r=Skeletons.__new__(Skeletons);r.data=bytes(data)
        for i,name in enumerate(names):
            self.assertEqual(dictionary_lookup(r,dictionary,name),11001+i)
        for name in ('missing','ABCD','RW102W104',''):
            self.assertIsNone(dictionary_lookup(r,dictionary,name))

    def test_rename_preserves_fields_and_rebuilds_lookup(self):
        before=valid_fixture()
        after,report=rename_bone(before,'CS_W1_World','root','stem')
        self.assertEqual(len(before),len(after))
        r=Skeletons(after)
        self.assertEqual(r.unique('stem').offset,0x1c0)
        self.assertEqual(dictionary_lookup(r,0x180,'stem'),0x1c0)
        self.assertIsNone(dictionary_lookup(r,0x180,'root'))
        allowed=set()
        for p in report['string_offsets']:allowed.update(range(p,p+4))
        for i in range(2):allowed.update(range(0x188+16*i,0x190+16*i))
        self.assertTrue(all(a==b or i in allowed for i,(a,b) in enumerate(zip(before,after))))
        self.assertEqual(before[0x1c0:0x200],after[0x1c0:0x200])

    def test_rejects_shared_references_and_length_changes(self):
        b=bytearray(valid_fixture());r=Skeletons(bytes(b));target=r.ptr(0x1c0)
        struct.pack_into('>I',b,0xf00,(target-0xf00)&0xffffffff)
        with self.assertRaisesRegex(ValueError,'shared references'):
            rename_bone(bytes(b),'CS_W1_World','root','stem')
        with self.assertRaisesRegex(ValueError,'equal-length'):
            rename_bone(valid_fixture(),'CS_W1_World','root','longer')
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            build_trie(['A','A'])

    def test_rejects_existing_bone_name_collision(self):
        b=bytearray(valid_fixture())
        struct.pack_into('>H',b,0x148,2)
        struct.pack_into('>I',b,0x184,2)
        b[0xf80:0xf85]=b'stem\0'
        # Add a second synthetic bone and key while preserving the first.
        b[0x200:0x240]=b[0x1c0:0x200]
        struct.pack_into('>I',b,0x200,0xf80-0x200)
        struct.pack_into('>H',b,0x204,1)
        struct.pack_into('>I',b,0x1b0,0xf80-0x1b0)
        struct.pack_into('>I',b,0x1b4,0x200-0x1b4)
        for i,node in enumerate(build_trie(['root','stem'])):
            struct.pack_into('>IHH',b,0x188+16*i,*node)
        with self.assertRaisesRegex(ValueError,'collision'):
            rename_bone(bytes(b),'CS_W1_World','root','stem')


class LocalRenameTests(unittest.TestCase):
    def test_real_w1_fixed_length_rename_in_memory(self):
        source=Path(__file__).resolve().parents[1]/'NSMBU Modding Project/content/Common/course_select/CS_W1.szs'
        if not source.is_file():self.skipTest('User-provided local dump unavailable')
        original=source.read_bytes();fingerprint=hashlib.sha256(original).digest()
        before=Archive(original).read('CS_W1.bfres')
        after,report=rename_bone(before,'CS_W1','RW102W1T0','RW102W103')
        r=Skeletons(before);updated=Skeletons(after)
        self.assertEqual(len(before),len(after))
        a,b=r.unique('RW102W1T0'),updated.unique('RW102W103')
        self.assertEqual((a.offset,a.position,a.index,a.parent),(b.offset,b.position,b.index,b.parent))
        self.assertEqual(report['relative_references'],[0x3128,0x62e8])
        allowed=bytearray(len(before))
        for p in report['string_offsets']:allowed[p:p+9]=b'\1'*9
        dictionary=report['dictionary_offset']
        for i in range(report['dictionary_entries']+1):
            p=dictionary+8+16*i;allowed[p:p+8]=b'\1'*8
        self.assertTrue(all(a==b or allowed[i] for i,(a,b) in enumerate(zip(before,after))))
        for name,bones in r.models.items():
            self.assertEqual(len(bones),len(updated.models[name]))
            for bone in bones:
                new=updated.unique('RW102W103' if bone.name=='RW102W1T0' else bone.name)
                self.assertEqual(before[bone.offset:bone.offset+64],after[new.offset:new.offset+64])
        self.assertEqual(hashlib.sha256(source.read_bytes()).digest(),fingerprint)


if __name__=='__main__':unittest.main()
