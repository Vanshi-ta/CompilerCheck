// compilercheck: category=arrays safety=well_defined expect_exit=0
#include <stdio.h>

#define N 4

int main(void) {
    int a[N][N], b[N][N], c[N][N];
    for (int i = 0; i < N; ++i)
        for (int j = 0; j < N; ++j) {
            a[i][j] = i + j;
            b[i][j] = i - j;
        }
    for (int i = 0; i < N; ++i)
        for (int j = 0; j < N; ++j) {
            c[i][j] = 0;
            for (int k = 0; k < N; ++k) c[i][j] += a[i][k] * b[k][j];
        }
    int trace = 0;
    for (int i = 0; i < N; ++i) trace += c[i][i];
    printf("%d\n", trace);
    return 0;
}
