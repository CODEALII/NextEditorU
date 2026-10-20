"""Bounded-window greedy Yaz0 encoder, using only the Python standard library.

Emits standard 4 KiB LZ77 backreferences with lengths 3..273. Hash chains
retain at most 4096 positions; the fixed hash table does not grow with input.
The 128-candidate search bound favors predictable runtime over optimal output.
"""
import struct


MAX_SIZE = 256 * 1024 * 1024


def encode(data: bytes) -> bytes:
    """Return a deterministic Yaz0 stream for bytes, including empty input."""
    if not isinstance(data, bytes):
        raise TypeError("Yaz0 input must be bytes")
    size = len(data)
    if size > MAX_SIZE:
        raise ValueError("Resource exceeds size limit")
    output = bytearray(b"Yaz0" + struct.pack(">I", size) + bytes(8))
    heads = [-1] * 65536
    previous = [-1] * 4096
    position = 0
    while position < size:
        code_offset = len(output)
        output.append(0)
        code = 0
        for bit in range(7, -1, -1):
            if position >= size:
                break
            limit = min(273, size - position)
            best_length, best_position = 2, -1
            if limit >= 3:
                key = ((data[position] * 251 + data[position + 1]) * 251 + data[position + 2]) & 65535
                candidate = heads[key]
                window_start = max(0, position - 4096)
                attempts = 0
                prefix = data[position:position + 3]
                while candidate >= window_start and candidate >= 0 and attempts < 128:
                    # A longer match must agree past the previous best match.
                    if data[candidate + best_length] == data[position + best_length] and data.startswith(prefix, candidate):
                        length = 3
                        while length < limit and data[candidate + length] == data[position + length]:
                            length += 1
                        if length > best_length:
                            best_length, best_position = length, candidate
                            if length == limit:
                                break
                    candidate = previous[candidate & 4095]
                    attempts += 1
            consumed = best_length if best_position >= 0 else 1
            if best_position < 0:
                code |= 1 << bit
                output.append(data[position])
            else:
                distance = position - best_position - 1
                if best_length >= 18:
                    output.extend((distance >> 8, distance & 255, best_length - 18))
                else:
                    output.extend((((best_length - 2) << 4) | (distance >> 8), distance & 255))
            # All consumed bytes enter the dictionary, including bytes emitted
            # by a reference; future references can start within that match.
            stop = min(position + consumed, size - 2)
            for inserted in range(position, stop):
                key = ((data[inserted] * 251 + data[inserted + 1]) * 251 + data[inserted + 2]) & 65535
                previous[inserted & 4095] = heads[key]
                heads[key] = inserted
            position += consumed
        output[code_offset] = code
    return bytes(output)
