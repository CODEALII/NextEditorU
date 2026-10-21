"""Fixed-allocation Wii U BFRES bone-name editing with Patricia trie rebuild.

Trie algorithm adapted from BfresLibrary Shared/Common/ResDict.cs,
UpdateNodes/GetDirection, commit 65c005275deed1e085069e72fea523247f955b87.

MIT License
Copyright (c) 2017-2018 Syroot

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""
import struct

from .bfres import Skeletons


def _direction(name, reference):
    byte, bit = reference >> 3, reference & 7
    return (ord(name[byte]) >> bit) & 1 if byte < len(name) else 0


def build_trie(names):
    """Return root+entries as (reference,left,right), retaining input order."""
    if len(names) > 65535 or len(set(names)) != len(names):
        raise ValueError('Duplicate or excessive dictionary keys')
    if any(not n or not n.isascii() or '\0' in n for n in names):
        raise ValueError('Nonempty ASCII dictionary names required')
    keys = [''] + list(names)
    nodes = [[0xffffffff, 0, 0] for _ in keys]
    for i in range(1,len(nodes)):
        key = keys[i]
        parent, child = 0, nodes[0][1]
        while nodes[parent][0] > nodes[child][0]:
            parent = child
            child = nodes[child][2 if _direction(key,nodes[child][0]) else 1]
        reference = max(len(key),len(keys[child]))*8
        while _direction(keys[child],reference) == _direction(key,reference):
            if not reference:
                raise ValueError('Duplicate dictionary key')
            reference -= 1
        nodes[i][0] = reference
        parent, child = 0, nodes[0][1]
        while nodes[parent][0] > nodes[child][0] and nodes[child][0] > reference:
            parent = child
            child = nodes[child][2 if _direction(key,nodes[child][0]) else 1]
        nodes[i][1:] = [child,i] if _direction(key,reference) else [i,child]
        nodes[parent][2 if _direction(key,nodes[parent][0]) else 1] = i
    return [tuple(node) for node in nodes]


def dictionary_lookup(reader, dictionary, name):
    """Use the serialized trie, not linear enumeration, returning a value offset."""
    count=reader.u32(dictionary+4)
    if count>65535:
        raise ValueError('Excessive dictionary size')
    reader.bounds(dictionary,8+16*(count+1))
    nodes=[struct.unpack_from('>IHH',reader.data,dictionary+8+16*i) for i in range(count+1)]
    if any(left>count or right>count for _,left,right in nodes) or nodes[0][0]!=0xffffffff:
        raise ValueError('Invalid Patricia trie indices or root')
    parent,child=0,nodes[0][1]
    for _ in range(count+2):
        if nodes[parent][0] <= nodes[child][0]:
            if not child:
                return None
            at=dictionary+8+16*child
            return reader.ptr(at+12) if reader.string(reader.ptr(at+8))==name else None
        parent=child
        child=nodes[child][2 if _direction(name,nodes[child][0]) else 1]
    raise ValueError('Patricia trie lookup exceeded traversal limit')


def rename_bone(data, model, old_name, new_name):
    """Return (patched_bytes, report), refusing ambiguous/shared string changes.

    Only equal-byte-length printable ASCII renames are permitted. Any aligned
    relative reference to the affected strings outside the bone-name/key fields
    aborts the operation, protecting animation and unrelated resource names.
    """
    if not old_name or not new_name or len(old_name)!=len(new_name) or not old_name.isascii() or not new_name.isascii() or any(ord(c)<33 or ord(c)>126 for c in old_name+new_name):
        raise ValueError('Rename requires equal-length nonempty printable ASCII names')
    r=Skeletons(data)
    if r.version!=0x03000001:
        raise ValueError('Bone renaming only supports BFRES version 0x03000001')
    models=dict(r.dictionary(r.ptr(32)))
    if model not in models:
        raise ValueError('Missing target model')
    skeleton=r.ptr(models[model]+12)
    dictionary=r.ptr(skeleton+16)
    entries=r.dictionary(dictionary)
    if old_name not in dict(entries):
        raise ValueError('Missing target bone name')
    if old_name==new_name:
        return data,{'model':model,'old':old_name,'new':new_name,'changed':False}
    if new_name in r.bones:
        raise ValueError('Bone name collision')
    for name,value in entries:
        if dictionary_lookup(r,dictionary,name)!=value:
            raise ValueError('Source bone dictionary trie lookup failed')
    idx=[name for name,_ in entries].index(old_name)
    key_field=dictionary+24+16*idx+8
    bone=dict(entries)[old_name]
    strings={r.ptr(key_field),r.ptr(bone)}
    expected_fields={key_field,bone}
    literal=old_name.encode()+b'\0'
    occurrences=set()
    at=0
    while True:
        at=data.find(literal,at)
        if at<0:break
        occurrences.add(at);at+=1
    if occurrences!=strings:
        raise ValueError('Bone name has additional shared or ambiguous string literals')
    references={p:[] for p in strings}
    for field in range(0,len(data)-3,4):
        raw=struct.unpack_from('>I',data,field)[0]
        target=(field+raw)&0xffffffff
        if raw and target in references:
            references[target].append(field)
    found={field for fields in references.values() for field in fields}
    if found!=expected_fields:
        raise ValueError('Bone string has additional shared references; refusing rename')
    names=[new_name if name==old_name else name for name,_ in entries]
    trie=build_trie(names)
    out=bytearray(data)
    for p in strings:
        out[p:p+len(new_name)]=new_name.encode()
    for i,node in enumerate(trie):
        struct.pack_into('>IHH',out,dictionary+8+16*i,*node)
    result=bytes(out)
    updated=Skeletons(result)
    for name,value in zip(names,[v for _,v in entries]):
        if dictionary_lookup(updated,dictionary,name)!=value:
            raise ValueError('Rebuilt dictionary lookup failed')
    if dictionary_lookup(updated,dictionary,old_name) is not None:
        raise ValueError('Old dictionary key still resolves')
    return result,{'model':model,'old':old_name,'new':new_name,'changed':True,
        'dictionary_entries':len(entries),'string_offsets':sorted(strings),
        'relative_references':sorted(found),'dictionary_offset':dictionary,
        'game_verified':False}
