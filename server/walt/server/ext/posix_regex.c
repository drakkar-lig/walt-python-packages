#include <stdlib.h>
#include <regex.h>
#include <stdbool.h>


void *_regcomp(char *regex) {
    regex_t *preg = malloc(sizeof(regex_t));

    if (regcomp(preg, regex, REG_EXTENDED | REG_NOSUB)) {
        free(preg);
        return NULL;
    }
    else {
        return (void*)preg;
    }
}

char *_regerror_alloc(char *regex) {
    regex_t *preg = malloc(sizeof(regex_t));
    char *buf = NULL;
    int bufsize, res;

    res = regcomp(preg, regex, REG_EXTENDED | REG_NOSUB);
    if (res != 0) {  // error
        bufsize = regerror(res, preg, NULL, 0);
        buf = malloc(bufsize);
        regerror(res, preg, buf, bufsize);
        free(preg);
        return buf;
    }
    else {          // no error!
        return NULL;
    }
}

int _regmatch(void *preg, char *s) {
    int res = regexec((regex_t*)preg, (const char*)s, 0, NULL, 0);
    return (res == 0);
}

void _regfree(void *preg) {
    regfree((regex_t*)preg);
    free(preg);
}
