import numpy as np
from scipy import sparse
import cffi

ffi = cffi.FFI()
ffi.cdef("""
    extern int cffi_prox_asaga(double* x, double* A_data, int64_t* A_indices, int64_t* A_indptr, double* b,
        double* d, int64_t n_samples, int64_t n_features, int64_t n_threads, double alpha, double beta,
        double step_size, int64_t max_iter, double* trace_x, double* trace_time, int64_t iter_freq);
    """)
import os
dir_path = os.path.dirname(os.path.realpath(__file__))
C = ffi.dlopen(dir_path + '/libasaga.so')  # @NOTE get shared library


def _compute_D(A):
    # .. estimate diagonal elements of the reweighting matrix (D) ..
    n_samples = A.shape[0]
    tmp = A.copy()
    tmp.data[:] = 1.
    d = np.array(tmp.sum(0), dtype=np.float).ravel()
    idx = (d != 0)
    d[idx] = n_samples / d[idx]
    d[~idx] = 0.
    return d


def _logistic_loss(A, b, alpha, beta, x):
    # loss function to be optimized, it's the logistic loss
    z = A.dot(x)
    yz = b * z
    idx = yz > 0
    out = np.zeros_like(yz)
    out[idx] = np.log(1 + np.exp(-yz[idx]))
    out[~idx] = (-yz[~idx] + np.log(1 + np.exp(yz[~idx])))
    out = out.mean() + .5 * alpha * x.dot(x) + beta * np.sum(np.abs(x))
    return out

def minimize_SAGA(A, b, alpha, beta, step_size, max_iter=100, n_jobs=1):
    # @NOTE max_iter: number of epochs
    n_samples, n_features = A.shape
    A = sparse.csr_matrix(A, dtype=np.float)
    indices = A.indices.astype(np.int64)
    indptr = A.indptr.astype(np.int64)
    x = np.zeros(n_features)  # the iterate

    d = _compute_D(A)
    print('Delta (sparsity measure) = %s' % (1.0 / np.min(d[d != 0])))

    trace_x = np.zeros((max_iter + 1, n_features))  # seems that we have to save every x_t
    trace_time = np.zeros(max_iter + 1)
    C.cffi_prox_asaga(
        ffi.cast("double *", x.ctypes.data), ffi.cast("double *", A.data.ctypes.data),
        ffi.cast("int64_t *", indices.ctypes.data), ffi.cast("int64_t *", indptr.ctypes.data),
        ffi.cast("double *", b.ctypes.data), ffi.cast("double *", d.ctypes.data), n_samples, n_features,
        n_jobs, alpha, beta, step_size, max_iter, ffi.cast("double *", trace_x.ctypes.data),
        ffi.cast("double *", trace_time.ctypes.data), ffi.cast("int64_t", n_samples))
    print('.. computing trace ..')
    func_trace = np.array([
        _logistic_loss(A, b, alpha, beta, xi) for xi in trace_x])

    return x, trace_time[:-2], func_trace[:-2] # why the last two iterates are not returned


if __name__ == '__main__':
    from scipy import sparse
    import pylab as plt

    n_samples, n_features = int(1e5), int(1e6)
    X = sparse.random(n_samples, n_features, density=5. / n_samples)
    w = sparse.random(1, n_features, density=1e-3)
    y = np.sign(X.dot(w.T).toarray().ravel() + np.random.randn(n_samples))  # y = sign(X w + noise)
    n_samples, n_features = X.shape # why we need to reset n_samples and n_features ???
    beta = 1e-10  # l1-coef
    alpha = 1. / n_samples  # strong convexity coefficient (l2-coef)

    L = 0.25 * np.max(X.multiply(X).sum(axis=1)) + alpha * n_samples # compute Lipschitz constant, but @NOTE why alpha * n_samples instead of alpha???
    print('data loaded')

    step_size_SAGA = 1.0 / (3 * L)
    markers = ['^', 'h', 'o', 's', 'x']
    for i, n_jobs in enumerate([1, 2, 3, 4]):  # the enumerate() function adds a counter (start from 0) to an iterable
        print('Running %s jobs' % n_jobs)
        x, trace_time, func_trace = minimize_SAGA(
            X, y, alpha, beta, step_size_SAGA, max_iter=int(200 / n_jobs), n_jobs=n_jobs)
        fmin = np.min(func_trace)
        plt.plot(trace_time, func_trace - fmin, label='using %s cores' % n_jobs, marker=markers[i], markersize=10, lw=3)
    plt.grid()
    plt.legend()
    plt.xlim((0, trace_time[-1] * .7))
    plt.ylim(ymin=1e-6)
    plt.yscale('log')
    plt.show()
