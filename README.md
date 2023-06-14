# umm-v-gen
UMM-Var Metadata Generator for PO.DAAC

## python

Run the script from any Python 3.6+ environment with all [dependencies](app/requirements.txt) satisfied:
```shell
python app/ummvar_gen.py 20230101004501-JPL-L2P_GHRSST-SSTskin-MODIS_A-N-v02.0-fv01.0.nc
```

The command above will output a json list of UMM-Var records, one for each variable/dataset in the source netcdf4/hdf5 file.

Provide the concept-id of the target CMR collection to the `-c` parameter to attempt to ingest the generated variable records to CMR.

## docker

Use docker to build and run a containerized version of the script from any machine with docker engine installed.

1. Run the following command from the repository root to build a local docker image and test the containerized script against the test granule specified in [.docker/.env](.docker/.env):
```shell
bash .docker/build.sh
```
Check the log in `.docker/build.log` if errors are reported to your shell.

2. Successful builds conclude by writing a wrapper script [.docker/ummv](.docker/ummv) to execute the containerized Python script within an ephemeral container. The user's input arguments are passed transparently to the script.

This command is equivalent to the example above:

```shell
.docker/ummv 20230101004501-JPL-L2P_GHRSST-SSTskin-MODIS_A-N-v02.0-fv01.0.nc
```

__Important usage note:__

You must set the path to a local certs file directory (`CERTS_DIR`) and a local test granule (`TESTS_GRAN`) in [.docker/.env](.docker/.env) before running [.docker/build.sh](.docker/build.sh) to build with CMR ingest support:
```bash
CERTS_DIR=
TESTS_GRAN=
```
Contact [Jack McNelis](jmcnelis@jpl.nasa.gov) for more information about the format/content of the local certs file.
