import functools
import operator
import os
from typing import Dict, Optional, List, Tuple
import requests
import yaml

import torch_xla.utils.utils as xu
import torch_xla.core.xla_env_vars as xenv

_GCE_METADATA_ROOT_URL = 'http://metadata.google.internal/computeMetadata/v1'
_ACCELERATOR_TYPE_TO_HOST_BOUNDS = {
    # v2
    'v2-8': '1,1,1',
    'v2-32': '2,2,1',
    'v2-128': '4,4,1',
    'v2-256': '4,8,1',
    'v2-512': '8,8,1',
    # v3
    'v3-8': '1,1,1',
    'v3-32': '2,2,1',
    'v3-64': '2,4,1',
    'v3-128': '4,4,1',
    'v3-256': '4,8,1',
    'v3-512': '8,8,1',
    'v3-1024': '8,16,1',
    'v3-2048': '16,16,1',
}

MeshShape = Tuple[int, int, int]


def _parse_mesh_shape(mesh: str) -> MeshShape:
  dims = tuple(int(d) for d in mesh.split(','))
  if len(dims) != 3:
    raise ValueError("Mesh shape '{}' should be length 3".format(mesh))

  return dims


def _multiply_mesh_shapes(mesh1: MeshShape, mesh2: MeshShape) -> MeshShape:
  return tuple(d1 * d2 for d1, d2 in zip(mesh1, mesh2))


def _mesh_size(mesh: MeshShape) -> int:
  return functools.reduce(operator.mul, mesh)


def _get_metadata(key: str) -> str:
  path = os.path.join(_GCE_METADATA_ROOT_URL, 'instance/attributes', key)
  resp = requests.get(path, headers={'Metadata-Flavor': 'Google'})
  resp.raise_for_status()

  return resp.text


def num_processes(default: int = 4) -> Optional[int]:
  process_bounds = xu.getenv_as(xenv.TPU_PROCESS_BOUNDS, str)

  return _mesh_size(
      _parse_mesh_shape(process_bounds)) if process_bounds else default


def num_local_processes() -> Optional[int]:
  # Don't create more processes than local chips (4)
  return min(4, num_processes())


def task_id() -> Optional[int]:
  return xu.getenv_as(xenv.CLOUD_TPU_TASK_ID, int)


def get_tpu_env() -> Dict[str, str]:
  metadata = _get_metadata('tpu-env')

  return yaml.load(metadata, yaml.Loader)


def get_worker_ips() -> List[str]:
  metadata = _get_metadata('worker-network-endpoints')

  # Workers have format 'hostname:uid:ip,hostname:uid:ip,...'
  workers = metadata.split(',')
  ips = [worker.split(':')[2] for worker in workers]

  return ips if len(ips) > 1 else ['localhost']


def configure_topology(local_rank: int,
                       local_world_size: int,
                       base_port: int = 8476):
  tpu_env = get_tpu_env()

  accelerator_type = tpu_env['ACCELERATOR_TYPE']
  if tpu_env['ACCELERATOR_TYPE'].startswith('v4'):
    # Process bounds with 4 chips per process
    default_process_bounds = _parse_mesh_shape(tpu_env[xenv.TPU_PROCESS_BOUNDS])
    chips_per_process = _parse_mesh_shape(
        tpu_env[xenv.TPU_CHIPS_PER_PROCESS_BOUNDS])
  else:
    # TODO: merge with TPU v4 case when bounds are added to metadata
    default_process_bounds = _parse_mesh_shape(
        _ACCELERATOR_TYPE_TO_HOST_BOUNDS[accelerator_type])
    chips_per_process = _parse_mesh_shape('2,2,1')

  # Process bounds with 1 chip per process
  process_bounds = _multiply_mesh_shapes(default_process_bounds,
                                         chips_per_process)

  os.environ.setdefault(xenv.TPU_CHIPS_PER_PROCESS_BOUNDS, '1,1,1')
  os.environ.setdefault(xenv.TPU_PROCESS_BOUNDS,
                        ','.join(str(dim) for dim in process_bounds))

  # Assume each TPU has the same number of local processes with the same ports
  worker_id = int(tpu_env['WORKER_ID'])
  os.environ.setdefault(xenv.CLOUD_TPU_TASK_ID,
                        str(worker_id * local_world_size + local_rank))

  worker_ips = get_worker_ips()

  ports = list(range(base_port, base_port + local_world_size))
  process_endpoints = [
      ','.join(f'{ip}:{port}' for port in ports) for ip in worker_ips
  ]
  os.environ.setdefault(xenv.TPU_PROCESS_ADDRESSES, ','.join(process_endpoints))

  os.environ.setdefault(xenv.TPU_VISIBLE_DEVICES, str(local_rank))
  os.environ.setdefault(xenv.TPU_PROCESS_PORT, str(ports[local_rank]))