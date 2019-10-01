#include "torch_xla/csrc/torch_util.h"

#include "tensorflow/compiler/xla/xla_client/debug_macros.h"

namespace torch_xla {

at::Tensor CopyTensor(const at::Tensor& ref) {
  return ref.to(ref.options(), /*non_blocking=*/false, /*copy=*/true);
}

// Same as above, with an additional cast.
at::Tensor CopyTensor(const at::Tensor& ref, at::ScalarType dest_type) {
  return ref.to(ref.options().dtype(dest_type), /*non_blocking=*/false,
                /*copy=*/true);
}

at::ScalarType GetScalarType(at::Scalar scalar) {
  if (scalar.isFloatingPoint()) {
    return at::kDouble;
  } else if (scalar.isIntegral(/*includeBool=*/false)) {
    return at::kLong;
  } else if (scalar.isBoolean()) {
    return at::kBool;
  } else if (scalar.isComplex()) {
    return at::kComplexDouble;
  }
  XLA_ERROR() << "Unknown type for scalar";
}

}  // namespace torch_xla
