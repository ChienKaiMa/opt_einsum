import numpy as np
import pytest

from opt_einsum import backends, contract, contract_expression, helpers, sharing
from opt_einsum.contract import Shaped, infer_backend, parse_backend

try:
    import cupy

    found_cupy = True
except ImportError:
    found_cupy = False

try:
    import tensorflow as tf

    # needed so tensorflow doesn't allocate all gpu mem
    try:
        from tensorflow import ConfigProto
    except ImportError:
        from tf.compat.v1 import ConfigProto
    _TF_CONFIG = ConfigProto()
    _TF_CONFIG.gpu_options.allow_growth = True
    found_tensorflow = True
except ImportError:
    found_tensorflow = False

try:
    import os

    os.environ["MKL_THREADING_LAYER"] = "GNU"
    import theano

    found_theano = True
except ImportError:
    found_theano = False

try:
    import torch

    found_torch = True
except ImportError:
    found_torch = False

try:
    import jax

    found_jax = True
except ImportError:
    found_jax = False

try:
    import autograd

    found_autograd = True
except ImportError:
    found_autograd = False

tests = [
    "ab,bc->ca",
    "abc,bcd,dea",
    "abc,def->fedcba",
    "abc,bcd,df->fa",
    # test 'prefer einsum' ops
    "ijk,ikj",
    "i,j->ij",
    "ijk,k->ij",
    "AB,BC->CA",
]


@pytest.mark.skipif(not found_tensorflow, reason="Tensorflow not installed.")
@pytest.mark.parametrize("string", tests)
def test_tensorflow(string):
    views = helpers.build_views(string)
    ein = contract(string, *views, optimize=False, use_blas=False)
    opt = np.empty_like(ein)

    shps = [v.shape for v in views]
    expr = contract_expression(string, *shps, optimize=True)

    sess = tf.Session(config=_TF_CONFIG)
    with sess.as_default():
        expr(*views, backend="tensorflow", out=opt)
    sess.close()

    assert np.allclose(ein, opt)

    # test non-conversion mode
    tensorflow_views = [backends.to_tensorflow(view) for view in views]
    expr(*tensorflow_views)


@pytest.mark.skipif(not found_tensorflow, reason="Tensorflow not installed.")
@pytest.mark.parametrize("constants", [{0, 1}, {0, 2}, {1, 2}])
def test_tensorflow_with_constants(constants):
    eq = "ij,jk,kl->li"
    shapes = (2, 3), (3, 4), (4, 5)
    (non_const,) = {0, 1, 2} - constants
    ops = [np.random.rand(*shp) if i in constants else shp for i, shp in enumerate(shapes)]
    var = np.random.rand(*shapes[non_const])
    res_exp = contract(eq, *(ops[i] if i in constants else var for i in range(3)))

    expr = contract_expression(eq, *ops, constants=constants)

    # check tensorflow
    with tf.Session(config=_TF_CONFIG).as_default():
        res_got = expr(var, backend="tensorflow")
    assert all(
        array is None or infer_backend(array) == "tensorflow" for array in expr._evaluated_constants["tensorflow"]
    )
    assert np.allclose(res_exp, res_got)

    # check can call with numpy still
    res_got2 = expr(var, backend="numpy")
    assert np.allclose(res_exp, res_got2)

    # check tensorflow call returns tensorflow still
    res_got3 = expr(backends.to_tensorflow(var))
    assert isinstance(res_got3, tf.Tensor)


@pytest.mark.skipif(not found_tensorflow, reason="Tensorflow not installed.")
@pytest.mark.parametrize("string", tests)
def test_tensorflow_with_sharing(string):
    views = helpers.build_views(string)
    ein = contract(string, *views, optimize=False, use_blas=False)

    shps = [v.shape for v in views]
    expr = contract_expression(string, *shps, optimize=True)

    sess = tf.Session(config=_TF_CONFIG)

    with sess.as_default(), sharing.shared_intermediates() as cache:
        tfl1 = expr(*views, backend="tensorflow")
        assert sharing.get_sharing_cache() is cache
        cache_sz = len(cache)
        assert cache_sz > 0
        tfl2 = expr(*views, backend="tensorflow")
        assert len(cache) == cache_sz

    assert all(isinstance(t, tf.Tensor) for t in cache.values())

    assert np.allclose(ein, tfl1)
    assert np.allclose(ein, tfl2)


@pytest.mark.skipif(not found_theano, reason="Theano not installed.")
@pytest.mark.parametrize("string", tests)
def test_theano(string):
    views = helpers.build_views(string)
    ein = contract(string, *views, optimize=False, use_blas=False)
    shps = [v.shape for v in views]

    expr = contract_expression(string, *shps, optimize=True)

    opt = expr(*views, backend="theano")
    assert np.allclose(ein, opt)

    # test non-conversion mode
    theano_views = [backends.to_theano(view) for view in views]
    theano_opt = expr(*theano_views)
    assert isinstance(theano_opt, theano.tensor.TensorVariable)


@pytest.mark.skipif(not found_theano, reason="theano not installed.")
@pytest.mark.parametrize("constants", [{0, 1}, {0, 2}, {1, 2}])
def test_theano_with_constants(constants):
    eq = "ij,jk,kl->li"
    shapes = (2, 3), (3, 4), (4, 5)
    (non_const,) = {0, 1, 2} - constants
    ops = [np.random.rand(*shp) if i in constants else shp for i, shp in enumerate(shapes)]
    var = np.random.rand(*shapes[non_const])
    res_exp = contract(eq, *(ops[i] if i in constants else var for i in range(3)))

    expr = contract_expression(eq, *ops, constants=constants)

    # check theano
    res_got = expr(var, backend="theano")
    assert all(array is None or infer_backend(array) == "theano" for array in expr._evaluated_constants["theano"])
    assert np.allclose(res_exp, res_got)

    # check can call with numpy still
    res_got2 = expr(var, backend="numpy")
    assert np.allclose(res_exp, res_got2)

    # check theano call returns theano still
    res_got3 = expr(backends.to_theano(var))
    assert isinstance(res_got3, theano.tensor.TensorVariable)


@pytest.mark.skipif(not found_theano, reason="Theano not installed.")
@pytest.mark.parametrize("string", tests)
def test_theano_with_sharing(string):
    views = helpers.build_views(string)
    ein = contract(string, *views, optimize=False, use_blas=False)

    shps = [v.shape for v in views]
    expr = contract_expression(string, *shps, optimize=True)

    with sharing.shared_intermediates() as cache:
        thn1 = expr(*views, backend="theano")
        assert sharing.get_sharing_cache() is cache
        cache_sz = len(cache)
        assert cache_sz > 0
        thn2 = expr(*views, backend="theano")
        assert len(cache) == cache_sz

    assert all(isinstance(t, theano.tensor.TensorVariable) for t in cache.values())

    assert np.allclose(ein, thn1)
    assert np.allclose(ein, thn2)


@pytest.mark.skipif(not found_cupy, reason="Cupy not installed.")
@pytest.mark.parametrize("string", tests)
def test_cupy(string):  # pragma: no cover
    views = helpers.build_views(string)
    ein = contract(string, *views, optimize=False, use_blas=False)
    shps = [v.shape for v in views]

    expr = contract_expression(string, *shps, optimize=True)

    opt = expr(*views, backend="cupy")
    assert np.allclose(ein, opt)

    # test non-conversion mode
    cupy_views = [backends.to_cupy(view) for view in views]
    cupy_opt = expr(*cupy_views)
    assert isinstance(cupy_opt, cupy.ndarray)
    assert np.allclose(ein, cupy.asnumpy(cupy_opt))


@pytest.mark.skipif(not found_cupy, reason="Cupy not installed.")
@pytest.mark.parametrize("constants", [{0, 1}, {0, 2}, {1, 2}])
def test_cupy_with_constants(constants):  # pragma: no cover
    eq = "ij,jk,kl->li"
    shapes = (2, 3), (3, 4), (4, 5)
    (non_const,) = {0, 1, 2} - constants
    ops = [np.random.rand(*shp) if i in constants else shp for i, shp in enumerate(shapes)]
    var = np.random.rand(*shapes[non_const])
    res_exp = contract(eq, *(ops[i] if i in constants else var for i in range(3)))

    expr = contract_expression(eq, *ops, constants=constants)

    # check cupy
    res_got = expr(var, backend="cupy")
    # check cupy versions of constants exist
    assert all(array is None or infer_backend(array) == "cupy" for array in expr._evaluated_constants["cupy"])
    assert np.allclose(res_exp, res_got)

    # check can call with numpy still
    res_got2 = expr(var, backend="numpy")
    assert np.allclose(res_exp, res_got2)

    # check cupy call returns cupy still
    res_got3 = expr(cupy.asarray(var))
    assert isinstance(res_got3, cupy.ndarray)
    assert np.allclose(res_exp, res_got3.get())


@pytest.mark.skipif(not found_jax, reason="jax not installed.")
@pytest.mark.parametrize("string", tests)
def test_jax(string):  # pragma: no cover
    views = helpers.build_views(string)
    ein = contract(string, *views, optimize=False, use_blas=False)
    shps = [v.shape for v in views]

    expr = contract_expression(string, *shps, optimize=True)

    opt = expr(*views, backend="jax")
    assert np.allclose(ein, opt)
    assert isinstance(opt, np.ndarray)


@pytest.mark.skipif(not found_jax, reason="jax not installed.")
@pytest.mark.parametrize("constants", [{0, 1}, {0, 2}, {1, 2}])
def test_jax_with_constants(constants):  # pragma: no cover
    eq = "ij,jk,kl->li"
    shapes = (2, 3), (3, 4), (4, 5)
    (non_const,) = {0, 1, 2} - constants
    ops = [np.random.rand(*shp) if i in constants else shp for i, shp in enumerate(shapes)]
    var = np.random.rand(*shapes[non_const])
    res_exp = contract(eq, *(ops[i] if i in constants else var for i in range(3)))

    expr = contract_expression(eq, *ops, constants=constants)

    # check jax
    res_got = expr(var, backend="jax")
    # check jax versions of constants exist
    assert all(array is None or infer_backend(array).startswith("jax") for array in expr._evaluated_constants["jax"])

    assert np.allclose(res_exp, res_got)


@pytest.mark.skipif(not found_jax, reason="jax not installed.")
def test_jax_jit_gradient():
    eq = "ij,jk,kl->"
    shapes = (2, 3), (3, 4), (4, 2)
    views = [np.random.randn(*s) for s in shapes]
    expr = contract_expression(eq, *shapes)
    x0 = expr(*views)

    jit_expr = jax.jit(expr)
    x1 = jit_expr(*views).item()
    assert x1 == pytest.approx(x0, rel=1e-5)

    # jax only takes gradient w.r.t first argument
    grad_expr = jax.jit(jax.grad(lambda views: expr(*views)))
    view_grads = grad_expr(views)
    assert all(v1.shape == v2.shape for v1, v2 in zip(views, view_grads))

    # taking a step along the gradient should reduce our 'loss'
    new_views = [v - 0.001 * dv for v, dv in zip(views, view_grads)]
    x2 = jit_expr(*new_views).item()
    assert x2 < x1


@pytest.mark.skipif(not found_autograd, reason="autograd not installed.")
def test_autograd_gradient():
    eq = "ij,jk,kl->"
    shapes = (2, 3), (3, 4), (4, 2)
    views = [np.random.randn(*s) for s in shapes]
    expr = contract_expression(eq, *shapes)
    x0 = expr(*views)

    # autograd only takes gradient w.r.t first argument
    grad_expr = autograd.grad(lambda views: expr(*views))
    view_grads = grad_expr(views)
    assert all(v1.shape == v2.shape for v1, v2 in zip(views, view_grads))

    # taking a step along the gradient should reduce our 'loss'
    new_views = [v - 0.001 * dv for v, dv in zip(views, view_grads)]
    x1 = expr(*new_views)
    assert x1 < x0


@pytest.mark.parametrize("string", tests)
def test_dask(string):
    da = pytest.importorskip("dask.array")

    views = helpers.build_views(string)
    ein = contract(string, *views, optimize=False, use_blas=False)
    shps = [v.shape for v in views]
    expr = contract_expression(string, *shps, optimize=True)

    # test non-conversion mode
    da_views = [da.from_array(x, chunks=(2)) for x in views]
    da_opt = expr(*da_views)

    # check type is maintained when not using numpy arrays
    assert isinstance(da_opt, da.Array)

    assert np.allclose(ein, np.array(da_opt))

    # try raw contract
    da_opt = contract(string, *da_views)
    assert isinstance(da_opt, da.Array)
    assert np.allclose(ein, np.array(da_opt))


@pytest.mark.parametrize("string", tests)
def test_sparse(string):
    sparse = pytest.importorskip("sparse")

    views = helpers.build_views(string)

    # sparsify views so they don't become dense during contraction
    for view in views:
        np.random.seed(42)
        mask = np.random.choice([False, True], view.shape, True, [0.05, 0.95])
        view[mask] = 0

    ein = contract(string, *views, optimize=False, use_blas=False)
    shps = [v.shape for v in views]
    expr = contract_expression(string, *shps, optimize=True)

    # test non-conversion mode
    sparse_views = [sparse.COO.from_numpy(x) for x in views]
    sparse_opt = expr(*sparse_views)

    # check type is maintained when not using numpy arrays
    assert isinstance(sparse_opt, sparse.COO)

    assert np.allclose(ein, sparse_opt.todense())

    # try raw contract
    sparse_opt = contract(string, *sparse_views)
    assert isinstance(sparse_opt, sparse.COO)
    assert np.allclose(ein, sparse_opt.todense())


@pytest.mark.skipif(not found_torch, reason="Torch not installed.")
@pytest.mark.parametrize("string", tests)
def test_torch(string):

    views = helpers.build_views(string)
    ein = contract(string, *views, optimize=False, use_blas=False)
    shps = [v.shape for v in views]

    expr = contract_expression(string, *shps, optimize=True)

    opt = expr(*views, backend="torch")
    assert np.allclose(ein, opt)

    # test non-conversion mode
    torch_views = [backends.to_torch(view) for view in views]
    torch_opt = expr(*torch_views)
    assert isinstance(torch_opt, torch.Tensor)
    assert np.allclose(ein, torch_opt.cpu().numpy())


@pytest.mark.skipif(not found_torch, reason="Torch not installed.")
@pytest.mark.parametrize("constants", [{0, 1}, {0, 2}, {1, 2}])
def test_torch_with_constants(constants):
    eq = "ij,jk,kl->li"
    shapes = (2, 3), (3, 4), (4, 5)
    (non_const,) = {0, 1, 2} - constants
    ops = [np.random.rand(*shp) if i in constants else shp for i, shp in enumerate(shapes)]
    var = np.random.rand(*shapes[non_const])
    res_exp = contract(eq, *(ops[i] if i in constants else var for i in range(3)))

    expr = contract_expression(eq, *ops, constants=constants)

    # check torch
    res_got = expr(var, backend="torch")
    assert all(array is None or infer_backend(array) == "torch" for array in expr._evaluated_constants["torch"])
    assert np.allclose(res_exp, res_got)

    # check can call with numpy still
    res_got2 = expr(var, backend="numpy")
    assert np.allclose(res_exp, res_got2)

    # check torch call returns torch still
    res_got3 = expr(backends.to_torch(var))
    assert isinstance(res_got3, torch.Tensor)
    res_got3 = res_got3.numpy() if res_got3.device.type == "cpu" else res_got3.cpu().numpy()
    assert np.allclose(res_exp, res_got3)


def test_auto_backend_custom_array_no_tensordot():
    x = Shaped((1, 2, 3))
    # Shaped is an array-like object defined by opt_einsum - which has no TDOT
    assert infer_backend(x) == "opt_einsum"
    assert parse_backend([x], "auto") == "numpy"


@pytest.mark.parametrize("string", tests)
def test_object_arrays_backend(string):
    views = helpers.build_views(string)
    ein = contract(string, *views, optimize=False, use_blas=False)
    assert ein.dtype != object

    shps = [v.shape for v in views]
    expr = contract_expression(string, *shps, optimize=True)

    obj_views = [view.astype(object) for view in views]

    # try raw contract
    obj_opt = contract(string, *obj_views, backend="object")
    assert obj_opt.dtype == object
    assert np.allclose(ein, obj_opt.astype(float))

    # test expression
    obj_opt = expr(*obj_views, backend="object")
    assert obj_opt.dtype == object
    assert np.allclose(ein, obj_opt.astype(float))
