import os
import platform
import psutil
import json
from datetime import datetime
import _Exe_Util
import wmi
from filelock import FileLock
import sys


def check_system_health():
    """Collect and save comprehensive computer specifications for every run.
    
    Features:
    - Always updates the shared JSON file (per run)
    - Uses file lock for safe concurrent writes
    - Saves to _Exe_Util.SHARED_DUMP_FOLDER/_internal reports/machine_data.json
    - Collects extensive hardware and system info:
        * CPU, GPU (with driver date, video processor, etc.), RAM, Storage (with model, type, interface, serial, system disk, etc.), OS, System age, Network, User, Python, etc.

    """
    # Shared file (keep this as requested)
    shared_folder = os.path.join(_Exe_Util.SHARED_DUMP_FOLDER, "_internal reports")
    # Robustly create the shared folder if it doesn't exist
    try:
        os.makedirs(shared_folder, exist_ok=True)
    except Exception as e:
        print("Could not create shared folder: {}".format(e))
        return {}
    machine_data_file = os.path.join(shared_folder, "machine_data.json")
    shared_lock = FileLock(machine_data_file + '.lock')

    computer_name = platform.node()
    w = wmi.WMI()

    # CPU info
    cpu_info = w.Win32_Processor()[0]
    cpu_data = {
        "model": cpu_info.Name,
        "cores": cpu_info.NumberOfCores,
        "threads": cpu_info.NumberOfLogicalProcessors,
        "frequency": "{} MHz".format(cpu_info.MaxClockSpeed)
    }

    # GPU info (richer)
    gpu_data = []
    for gpu in w.Win32_VideoController():
        if gpu.Name != "Microsoft Basic Display Driver":
            gpu_memory = "Unknown"
            if gpu.AdapterRAM:
                gpu_memory = "{:.1f} GB".format(gpu.AdapterRAM / (1024**3))
            gpu_data.append({
                "name": gpu.Name,
                "memory": gpu_memory,
                "driver_version": getattr(gpu, 'DriverVersion', None),
                "driver_date": getattr(gpu, 'DriverDate', None),
                "video_processor": getattr(gpu, 'VideoProcessor', None),
                "refresh_rate": getattr(gpu, 'CurrentRefreshRate', None),
                "video_mode": getattr(gpu, 'VideoModeDescription', None),
                "hardware_reserved_memory": getattr(gpu, 'HardwareReservedMemory', None),
                "temperature_c": getattr(gpu, 'CurrentTemperature', None),
                "directx_version": getattr(gpu, 'DirectXVersion', None)
            })

    # Storage info (richer)
    # Map logical disks to physical disks
    logical_to_physical = {}
    for link in w.Win32_LogicalDiskToPartition():
        logical = link.Dependent.DeviceID
        partition = link.Antecedent.DeviceID
        logical_to_physical[logical] = partition
    partition_to_disk = {}
    for link in w.Win32_DiskDriveToDiskPartition():
        disk = link.Antecedent.DeviceID
        partition = link.Dependent.DeviceID
        partition_to_disk[partition] = disk
    disk_info_map = {}
    for disk in w.Win32_DiskDrive():
        disk_info_map[disk.DeviceID] = {
            "model": getattr(disk, 'Model', None),
            "media_type": getattr(disk, 'MediaType', None),
            "interface_type": getattr(disk, 'InterfaceType', None),
            "serial": getattr(disk, 'SerialNumber', None),
            "size_gb": float(disk.Size) / (1024**3) if disk.Size else None,
            "system_disk": getattr(disk, 'SystemName', None),
            "partitions": [p.DeviceID for p in disk.associators("Win32_DiskDriveToDiskPartition")]
        }
    storage_data = []
    for logical in w.Win32_LogicalDisk(DriveType=3):
        total = int(logical.Size) if logical.Size else 0
        free = int(logical.FreeSpace) if logical.FreeSpace else 0
        used = total - free
        used_percent = "Unknown"
        if total > 0:
            used_percent = "{:.1f}%".format(used/total*100)
        partition = logical_to_physical.get(logical.DeviceID)
        disk_id = partition_to_disk.get(partition)
        disk_info = disk_info_map.get(disk_id, {})
        storage_data.append({
            "drive": logical.DeviceID,
            "total": "{:.1f} GB".format(total / (1024**3)),
            "free": "{:.1f} GB".format(free / (1024**3)),
            "used": "{:.1f} GB".format(used / (1024**3)),
            "used_percent": used_percent,
            "model": disk_info.get("model"),
            "media_type": disk_info.get("media_type"),
            "interface_type": disk_info.get("interface_type"),
            "serial": disk_info.get("serial"),
            "size_gb": disk_info.get("size_gb"),
            "system_disk": disk_info.get("system_disk"),
            "partitions": disk_info.get("partitions")
        })

    # RAM info
    memory = psutil.virtual_memory()
    ram_data = {
        "total": "{:.1f} GB".format(memory.total / (1024**3)),
        "available": "{:.1f} GB".format(memory.available / (1024**3)),
        "used_percent": "{}%".format(memory.percent)
    }

    # System age
    try:
        os_install_date = w.Win32_OperatingSystem()[0].InstallDate
        install_date = datetime.strptime(os_install_date.split('.')[0], '%Y%m%d%H%M%S')
        system_age = (datetime.now() - install_date).days
    except:
        system_age = "Unknown"

    # Network info
    try:
        ip_addrs = psutil.net_if_addrs()
        network_data = {iface: [s.address for s in addrs if s.family == 2] for iface, addrs in ip_addrs.items()}
    except Exception as e:
        network_data = str(e)

    # User info
    user_data = {
        "user": os.getlogin(),
        "home": os.path.expanduser('~')
    }

    # Python info
    python_data = {
        "version": platform.python_version(),
        "executable": sys.executable
    }

    # Compile all data
    this_computer_data = {
        "cpu": cpu_data,
        "gpu": gpu_data,
        "storage": storage_data,
        "ram": ram_data,
        "system_age_days": system_age,
        "os": platform.platform(),
        "network": network_data,
        "user": user_data,
        "python": python_data,
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    # Only update the shared file for this test
    with shared_lock:
        try:
            if os.path.exists(machine_data_file):
                with open(machine_data_file, 'r', encoding='utf-8') as f:
                    all_data = json.load(f)
            else:
                all_data = {}
        except Exception:
            all_data = {}
        all_data[computer_name] = this_computer_data
        with open(machine_data_file, 'w', encoding='utf-8') as f:
            json.dump(all_data, f, indent=4, ensure_ascii=False)

    # 2026-03-25: InfraWatch POST removed — replaced by standalone
    # stdlib-only collector at Apps/lib/DumpScripts/collectors/collect_machine_spec.py
    # which runs via EA_Dist on all machines without needing DarkSide/ or .exe compile.

    return this_computer_data


if __name__ == "__main__":
    check_system_health()
