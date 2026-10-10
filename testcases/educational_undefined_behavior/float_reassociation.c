// compilercheck: category=undefined_behavior safety=undefined_behavior flags=-ffast-math description="fast-math reassociation"
// Not undefined behavior in the language sense, but -ffast-math lets the compiler reorder
// floating-point operations, so results may legitimately differ between optimization levels.
#include <stdio.h>

int main(void) {
    volatile float big = 1.0e8f;
    float sum = 0.0f;
    for (int i = 0; i < 1000; ++i) {
        sum += (i % 2 == 0) ? big : 1.0f;
    }
    printf("%.3f\n", sum);
    return 0;
}
