// compilercheck: category=integer_arithmetic safety=well_defined expect_exit=0 description="unsigned wraparound is defined"
#include <stdio.h>
#include <stdint.h>

int main(void) {
    uint32_t a = 4000000000u;
    uint32_t b = a + 500000000u;   /* wraps modulo 2^32 */
    uint32_t c = 5u - 10u;         /* wraps modulo 2^32 */
    printf("%u\n%u\n", b, c);
    return 0;
}
