# Prófanir

```bash
uv venv -p python3.13 .venv
uv pip install -p .venv pytest-homeassistant-custom-component gtfs-realtime-bindings
.venv/bin/python -m pytest
```

- `test_gtfs_rt.py`: GTFS-rt lesarinn borinn saman við opinberu protobuf-útfærsluna,
  vörpun yfir í vagna og komutíma, og hraði á 364 KB straumi.
- `test_integration.py`: viðbótin keyrð í Home Assistant með hermdu Swiftly API: JSON
  hafnað (401) → GTFS-rt, ógildur lykill, rusl í straumi, og JSON-hamurinn óbreyttur.
- `fixtures.py`: tilbúin leiðargögn fyrir leið 11 og GTFS-rt straumar.
