#!/usr/bin/env python3
"""Convert an uncompressed CHD v5 hard-disk image to a sparse raw image.

Why this exists
---------------
libchdman-rs 0.289 -- the backend behind `--features chd` -- rejects
*uncompressed* CHD v5 images with `InvalidFile`, even though they are valid and
are exactly what the documented authoring recipe produces:

    chdman createhd -o disk.chd -s <bytes> -ss 512 -c none

(see the comment block at the top of iris-irix65.toml). Compressed CHDs open
fine, so the failure is specific to `-c none`. Until that is fixed upstream,
converting to raw sidesteps it: iris reads raw images natively with no cargo
feature at all, and raw images also work with the COW overlay
(`overlay = true`).

Output is written sparsely -- holes where the CHD has zero hunks -- so a 14.8 GB
disk holding 1.7 GB of real data occupies 1.7 GB.

Usage:
    python3 tools/chd2raw.py <input.chd> <output.raw>
"""

import array
import os
import struct
import sys


def main(argv):
    if len(argv) != 3:
        sys.exit("usage: chd2raw.py <input.chd> <output.raw>")
    src, dst = argv[1], argv[2]

    f = open(src, "rb")
    h = f.read(124)
    if h[0:8] != b"MComprHD":
        sys.exit(f"{src}: not a CHD (bad magic)")
    if struct.unpack(">I", h[12:16])[0] != 5:
        sys.exit(f"{src}: only CHD v5 is handled")
    if any(struct.unpack(">4I", h[16:32])):
        sys.exit(f"{src}: compressed CHD -- iris reads these natively, "
                 "or convert with chdman")

    logical, mapoff, _metaoff = struct.unpack(">QQQ", h[32:56])
    hunkb = struct.unpack(">I", h[56:60])[0]
    nhunks = logical // hunkb

    f.seek(mapoff)
    hmap = array.array("I")
    hmap.frombytes(f.read(nhunks * 4))
    hmap.byteswap()  # CHD map is big-endian

    out = open(dst, "wb")
    i = 0
    data_hunks = 0
    hole_hunks = 0
    while i < nhunks:
        if hmap[i] == 0:                      # zero hunk -> leave a hole
            j = i
            while j < nhunks and hmap[j] == 0:
                j += 1
            out.seek((j - i) * hunkb, os.SEEK_CUR)
            hole_hunks += j - i
            i = j
            continue
        j = i                                 # coalesce a contiguous run
        while j + 1 < nhunks and hmap[j + 1] == hmap[j] + 1 and hmap[j + 1] != 0:
            j += 1
        cnt = j - i + 1
        f.seek(hmap[i] * hunkb)
        out.write(f.read(cnt * hunkb))
        data_hunks += cnt
        i = j + 1

    out.truncate(logical)                     # holes at EOF still count
    out.close()
    print(f"wrote {dst}: {logical:,} bytes logical, "
          f"{data_hunks:,} data hunks, {hole_hunks:,} sparse hunks")


if __name__ == "__main__":
    main(sys.argv)
