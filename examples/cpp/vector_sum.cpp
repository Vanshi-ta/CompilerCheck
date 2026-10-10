// compilercheck: category=functions safety=well_defined expect_exit=0
#include <cstdio>
#include <numeric>
#include <vector>

int main() {
    std::vector<int> v(100);
    std::iota(v.begin(), v.end(), 1);
    long total = std::accumulate(v.begin(), v.end(), 0L);
    std::printf("%ld\n", total);
    return 0;
}
