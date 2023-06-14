#!/bin/bash

# Force the script to quit evaluating if the current working directory is not named umm-v-gen:
ROOT_DIR=$( dirname $(cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd) ) && \
    cd "$ROOT_DIR" && \
    [[ $( basename $PWD ) -ne "umm-v-gen" ]] && \
    echo "Please execute build.sh from the repo root. Abort" && exit 1;

source ${1:-$ROOT_DIR/.docker/.env}

mv $PWD/.docker/build.log $PWD/.docker/build.log.old 2> /dev/null

touch $PWD/.docker/build.log

echo "# built on: $(date +'%Y-%m-%d %H:%M:%S') from '$(hostname)'" >> $PWD/.docker/build.log

# Download latest cf standard names xml into the app/resources/ directory:
curl -s https://cfconventions.org/Data/cf-standard-names/81/src/cf-standard-name-table.xml \
    -o $PWD/app/resources/cf-standard-name-table.xml

# Try to build the docker image:
printf "\n# build\n" | tee -a $PWD/.docker/build.log

docker build \
    -t umm-v-gen:testing \
    -f $PWD/.docker/Dockerfile \
    $PWD/ >> $PWD/.docker/build.log

# Try to print the help text for the python script inside the container:
printf "\n# test (print help)\n" | tee -a $PWD/.docker/build.log

docker run \
    --rm \
    --volume ${CERTS_DIR}/launchpad_token_ngap_ops.json:/launchpad_token_ngap_ops.json \
    --volume ${CERTS_DIR}/launchpad_token_ngap_uat.json:/launchpad_token_ngap_uat.json \
    --volume ${CERTS_DIR}/launchpad_token_ngap_sit.json:/launchpad_token_ngap_sit.json \
    umm-v-gen:testing --help >> $PWD/.docker/build.log

# Try to generate variables against the test granule (in .docker/.env):
printf "\n# test (create variables)\n" | tee -a $PWD/.docker/build.log

docker run \
    --rm \
    --volume ${CERTS_DIR}/launchpad_token_ngap_ops.json:/launchpad_token_ngap_ops.json \
    --volume ${CERTS_DIR}/launchpad_token_ngap_uat.json:/launchpad_token_ngap_uat.json \
    --volume ${CERTS_DIR}/launchpad_token_ngap_sit.json:/launchpad_token_ngap_sit.json \
    --volume $TESTS_GRAN:/source \
    umm-v-gen:testing >> $PWD/.docker/build.log

# If everything above executes without error, retag 'testing' to 'latest':
docker tag umm-v-gen:testing umm-v-gen:latest

# Echo wrapper to .docker/ummv; then, add to /usr/local/bin on the docker host!
echo "\
#!/bin/bash

GRAN=\"\${1}\"

[[ ! -f \$GRAN || -z \$GRAN ]] && \\
    printf '\nERROR: Argument 1 must be the path to an input granule!\n\n' && \\
    docker run --rm umm-v-gen:latest --help && \\
    exit 1;

ARGS=\"\${@:2}\"

docker run --rm \\
    --volume ${CERTS_DIR}/launchpad_token_ngap_ops.json:/launchpad_token_ngap_ops.json \\
    --volume ${CERTS_DIR}/launchpad_token_ngap_uat.json:/launchpad_token_ngap_uat.json \\
    --volume ${CERTS_DIR}/launchpad_token_ngap_sit.json:/launchpad_token_ngap_sit.json \\
    --volume \$(realpath \$GRAN):/source \\
    umm-v-gen:latest \$ARGS

exit 0;
" > $PWD/.docker/ummv && chmod +x $PWD/.docker/ummv
