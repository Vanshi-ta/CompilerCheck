// compilercheck: category=functions safety=well_defined expect_exit=0
#include <stdio.h>

static unsigned gcd(unsigned a, unsigned b) {
    return b == 0 ? a : gcd(b, a % b);
}

static unsigned long long fact(unsigned n) {
    return n <= 1 ? 1ull : n * fact(n - 1);
}

int main(void) {
    printf("%u\n%llu\n", gcd(1071u, 462u), fact(15));
    return 0;
}
