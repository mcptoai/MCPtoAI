"""Large inbound HEIC is disk-streamed, never a 50 MiB in-memory blob."""
import hashlib
import os
import tracemalloc
import pytest
from mcptoai_agent.inbound_transfer import InboundStaging, MAX_FILE_BYTES, MAX_CHUNK_BYTES, validate_heif_container


def large_heic_header(body_bytes):
    def box(t, data): return (len(data)+8).to_bytes(4,'big')+t+data
    ftyp=box(b'ftyp',b'heic\x00\x00\x00\x00mif1heic')
    meta=box(b'meta',b'\x00'*8)
    return ftyp+meta+(body_bytes+8).to_bytes(4,'big')+b'mdat'


def test_disk_staging_49_mib_original_digest_and_bounded_memory(tmp_path):
    size=49*1024*1024
    hdr=large_heic_header(size-48)
    # Ensure exact BMFF container header length from fixed ftyp and meta.
    payload=b'\x01'*MAX_CHUNK_BYTES
    header_len=len(hdr)
    header=large_heic_header(size-len(hdr))
    assert len(header)==header_len and len(header)==48
    digest=hashlib.sha256();digest.update(header)
    rest=size-len(header)
    # Hash independently without materializing the entire input.
    count=rest
    while count:
        part=payload[:min(count,len(payload))];digest.update(part);count-=len(part)
    stage=InboundStaging(expected_size=size,sha256=digest.hexdigest(),target=tmp_path/'large.heic')
    tracemalloc.start()
    stage.append(header)
    count=rest
    while count:
        part=payload[:min(count,len(payload))];stage.append(part);count-=len(part)
    assert stage.count==size
    stage.commit(approved=True,revalidate=lambda:True)
    _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    assert peak<8*1024*1024, f'In-memory peak exceeded 8 MiB: {peak}'
    assert stage.target.stat().st_size==size
    h=hashlib.sha256()
    with stage.target.open('rb') as f:
        for part in iter(lambda:f.read(MAX_CHUNK_BYTES),b''):h.update(part)
    assert h.hexdigest()==digest.hexdigest()


def test_exact_50_mib_allowed_and_one_byte_over_denied(tmp_path):
    stage=InboundStaging(expected_size=MAX_FILE_BYTES,sha256='a'*64,target=tmp_path/'ok.heic')
    stage.close()
    with pytest.raises(ValueError):
        InboundStaging(expected_size=MAX_FILE_BYTES+1,sha256='a'*64,target=tmp_path/'no.heic')
