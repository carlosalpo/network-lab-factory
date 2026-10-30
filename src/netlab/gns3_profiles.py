"""Explicit GNS3 3.0.6 / Nexo image mappings; no image download or template mutation."""

GNS3_PROFILES = {
    "iosv": {
        "image": "iosv-159-3.qcow2",
        "disk_interface": "virtio",
        "adapter_type": "e1000",
        "ram": 1024,
        "cpu": 1,
    },
    "iosvl2": {
        "image": "iosvl2-20200929.qcow2",
        "disk_interface": "virtio",
        "adapter_type": "e1000",
        "ram": 1024,
        "cpu": 1,
    },
    "csr": {
        "image": "csr1000vng-17.03.05.qcow2",
        "disk_interface": "virtio",
        "adapter_type": "vmxnet3",
        "ram": 4096,
        "cpu": 2,
    },
    "nxos": {
        "image": "nxosv9k-9300v-9.3.9.qcow2",
        "disk_interface": "sata",
        "adapter_type": "e1000",
        "ram": 8192,
        "cpu": 2,
        "bios": "OVMF-edk2-stable202305.fd",
    },
    "nxos105": {
        "image": "nxosv9k-9300v-10.5.3.F.qcow2",
        "disk_interface": "sata",
        "adapter_type": "e1000",
        "ram": 10240,
        "cpu": 4,
        "bios": "OVMF-edk2-stable202305.fd",
    },
    "asa": {
        "image": "asav-9-18-4.qcow2",
        "disk_interface": "virtio",
        "adapter_type": "virtio-net-pci",
        "ram": 2048,
        "cpu": 1,
    },
    "vpcs": {"image": "", "ram": 32, "cpu": 1},
}
