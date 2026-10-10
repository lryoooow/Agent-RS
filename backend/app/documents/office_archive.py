"""Validate actual Office ZIP expansion in bounded blocks before format parsers."""
from __future__ import annotations
import struct
import zipfile
import zlib
from io import BytesIO

_BLOCK = 64 * 1024


def validate_office_archive(data, settings, error):
    # Count actual central records before ZipFile allocates thousands of ZipInfo.
    end = data.rfind(b"PK\x05\x06", max(0, len(data)-65557))
    if end < 0 or end + 22 > len(data): raise zipfile.BadZipFile("missing directory")
    _, disk, cd_disk, disk_count, count, size, start, comment = struct.unpack_from("<4s4H2IH", data, end)
    if end+22+comment != len(data) or disk or cd_disk or disk_count != count:
        raise zipfile.BadZipFile("invalid directory")
    if count == 65535 or start+size != end: raise zipfile.BadZipFile("unsupported directory layout")
    pos, actual = start, 0
    while pos < end:
        if data[pos:pos+4] != b"PK\x01\x02" or pos+46 > end: raise zipfile.BadZipFile("invalid entry")
        name, extra, note = struct.unpack_from("<3H",data,pos+28)
        pos += 46+name+extra+note
        actual += 1
        if actual > settings.document_office_max_entries:
            raise error("OFFICE_ARCHIVE_TOO_MANY_ENTRIES", "Office document has too many archive entries.", 413)
    if pos != end or actual != count: raise zipfile.BadZipFile("entry count mismatch")
    with zipfile.ZipFile(BytesIO(data)) as archive:
        infos=archive.infolist()
        names=set()
        total=0
        for info in infos:
            if info.filename in names: raise zipfile.BadZipFile("duplicate entry")
            names.add(info.filename)
            total += info.file_size
            if total > settings.document_office_max_total_uncompressed_bytes:
                raise error("OFFICE_ARCHIVE_TOO_LARGE", "Office document exceeds the uncompressed size limit.", 413)
            if info.file_size > max(1,info.compress_size)*settings.document_office_max_entry_compression_ratio:
                raise error("OFFICE_ARCHIVE_COMPRESSION_RATIO", "Office archive entry exceeds the compression ratio limit.", 413)
            if info.file_size > settings.document_office_max_entry_bytes:
                raise error("OFFICE_ARCHIVE_ENTRY_TOO_LARGE", "Office archive entry exceeds the size limit.", 413)
        expanded_total=0
        for info in infos:
            offset=info.header_offset
            if data[offset:offset+4] != b"PK\x03\x04" or offset+30 > start:
                raise zipfile.BadZipFile("invalid local header")
            flags, method=struct.unpack_from("<2H",data,offset+6)
            name, extra=struct.unpack_from("<2H",data,offset+26)
            offset += 30+name+extra
            finish=offset+info.compress_size
            if flags & 1 or method != info.compress_type or finish > start:
                raise zipfile.BadZipFile("invalid compressed entry")
            if method not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED):
                raise zipfile.BadZipFile("unsupported Office compression")
            decoder=zlib.decompressobj(-15) if method==zipfile.ZIP_DEFLATED else None
            expanded, crc=0,0
            while offset < finish:
                pending=data[offset:min(finish,offset+_BLOCK)]
                offset += len(pending)
                while pending:
                    block=decoder.decompress(pending,_BLOCK) if decoder else pending
                    pending=decoder.unconsumed_tail if decoder else b""
                    expanded += len(block)
                    expanded_total += len(block)
                    if expanded_total > settings.document_office_max_total_uncompressed_bytes:
                        raise error("OFFICE_ARCHIVE_TOO_LARGE", "Actual Office expansion exceeds the size limit.", 413)
                    if expanded > settings.document_office_max_entry_bytes:
                        raise error("OFFICE_ARCHIVE_ENTRY_TOO_LARGE", "Actual archive entry exceeds the size limit.", 413)
                    if expanded > max(1,info.compress_size)*settings.document_office_max_entry_compression_ratio:
                        raise error("OFFICE_ARCHIVE_COMPRESSION_RATIO", "Actual Office expansion exceeds the ratio limit.", 413)
                    crc=zlib.crc32(block,crc)
                    if decoder and decoder.eof:
                        if pending or decoder.unused_data or offset != finish:
                            raise zipfile.BadZipFile("trailing compressed data")
                        break
            if (decoder and not decoder.eof) or expanded != info.file_size or crc != info.CRC:
                raise zipfile.BadZipFile("inconsistent expanded entry")
