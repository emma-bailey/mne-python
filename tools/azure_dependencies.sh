#!/bin/bash

set -eo pipefail
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
STD_ARGS="--progress-bar off --upgrade"
python -m pip install $STD_ARGS pip setuptools wheel
if [ "${TEST_MODE}" == "pip" ]; then
	# TODO: numpy<2 because of https://github.com/dipy/dipy/issues/3265
	python -m pip install $STD_ARGS --only-binary="numba,llvmlite,numpy,scipy,vtk,dipy" -e .[test,full] "numpy<2" "vtk<9.4"
elif [ "${TEST_MODE}" == "pip-pre" ]; then
	${SCRIPT_DIR}/install_pre_requirements.sh
	python -m pip install $STD_ARGS --pre -e .[test_extra]
else
	echo "Unknown run type ${TEST_MODE}"
	exit 1
fi
