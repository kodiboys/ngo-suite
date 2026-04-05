#!/bin/bash
# FILE: scripts/run_tests.sh
# MODULE: Test Suite Runner mit Coverage, Chaos Tests, Load Tests

set -e

echo "=========================================="
echo "TrueAngels Test Suite"
echo "=========================================="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
RUN_UNIT=true
RUN_INTEGRATION=true
RUN_CHAOS=false
RUN_LOAD=false
RUN_BENCHMARK=false
COVERAGE=true
PARALLEL=4

while [[ $# -gt 0 ]]; do
    case $1 in
        --unit-only)
            RUN_INTEGRATION=false
            shift
            ;;
        --integration-only)
            RUN_UNIT=false
            shift
            ;;
        --chaos)
            RUN_CHAOS=true
            shift
            ;;
        --load)
            RUN_LOAD=true
            shift
            ;;
        --benchmark)
            RUN_BENCHMARK=true
            shift
            ;;
        --no-coverage)
            COVERAGE=false
            shift
            ;;
        --parallel)
            PARALLEL="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

# Create test database
echo -e "${YELLOW}Setting up test database...${NC}"
docker-compose -f docker-compose.test.yml up -d postgres redis
sleep 5

# Run unit tests
if [ "$RUN_UNIT" = true ]; then
    echo -e "${YELLOW}Running unit tests...${NC}"
    if [ "$COVERAGE" = true ]; then
        pytest tests/test_unit/ -v -n $PARALLEL --cov=src --cov-report=html --cov-report=term --cov-report=xml
    else
        pytest tests/test_unit/ -v -n $PARALLEL
    fi
    echo -e "${GREEN}Unit tests passed!${NC}"
fi

# Run integration tests
if [ "$RUN_INTEGRATION" = true ]; then
    echo -e "${YELLOW}Running integration tests...${NC}"
    if [ "$COVERAGE" = true ]; then
        pytest tests/test_integration/ -v -n $PARALLEL --cov=src --cov-append
    else
        pytest tests/test_integration/ -v -n $PARALLEL
    fi
    echo -e "${GREEN}Integration tests passed!${NC}"
fi

# Run chaos tests
if [ "$RUN_CHAOS" = true ]; then
    echo -e "${YELLOW}Running chaos engineering tests...${NC}"
    pytest tests/test_chaos/ -v --chaos
    echo -e "${GREEN}Chaos tests passed!${NC}"
fi

# Run load tests
if [ "$RUN_LOAD" = true ]; then
    echo -e "${YELLOW}Running load tests...${NC}"
    pytest tests/test_performance/test_load.py -v --load
    echo -e "${GREEN}Load tests passed!${NC}"
fi

# Run benchmarks
if [ "$RUN_BENCHMARK" = true ]; then
    echo -e "${YELLOW}Running benchmarks...${NC}"
    pytest tests/ -v --benchmark-only --benchmark-autosave
    echo -e "${GREEN}Benchmarks complete!${NC}"
fi

# Show coverage report
if [ "$COVERAGE" = true ] && [ "$RUN_UNIT" = true ] || [ "$RUN_INTEGRATION" = true ]; then
    echo -e "${YELLOW}Coverage report:${NC}"
    coverage report --show-missing
    echo -e "${GREEN}Coverage report saved to htmlcov/index.html${NC}"
fi

# Cleanup
echo -e "${YELLOW}Cleaning up...${NC}"
docker-compose -f docker-compose.test.yml down

echo -e "${GREEN}=========================================="
echo -e "All tests passed!"
echo -e "==========================================${NC}"