// compilercheck: category=optimization_sensitive safety=well_defined expect_exit=0
#include <stdio.h>

int main(void) {
    volatile unsigned seed = 12345u;
    unsigned s = seed, acc = 0, dead = 0;
    for (unsigned i = 0; i < 1000; ++i) {
        acc += s * i;
        dead += acc * 3u;   /* never observed: optimizers may delete it */
        s = s * 1664525u + 1013904223u;
    }
    (void)dead;
    printf("%u\n", acc);
    return 0;
}
