// SPDX-License-Identifier: GPL-2.0-or-later
// Named Majora's Mask 3D title ids shared by the core, Qt and mm3d layers.
// Spec deviation: std::uint64_t instead of quint64, because core translation
// units (arm_dynarmic.cpp) compile without Qt headers; same 64-bit type.
#pragma once
#include <cstdint>
namespace MM3D {
inline constexpr std::uint64_t MajoraMask3DUsaTitle = 0x0004000000125500ULL;
inline constexpr std::uint64_t MajoraMask3DEurTitle = 0x0004000000125600ULL;
inline bool IsMajoraMask3DTitle(std::uint64_t id) {
    return id == MajoraMask3DUsaTitle || id == MajoraMask3DEurTitle;
}
}
