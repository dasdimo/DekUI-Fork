// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <atomic>
namespace MM3D::PlayerSettings {
// Render thread requests; the frontend applies/saves through its settings API.
inline std::atomic<int> resolution{4}, volume{100}, vsync{1}, cache{1};
inline std::atomic<int> set_resolution{-1}, set_volume{-1}, set_vsync{-1}, set_cache{-1};
inline std::atomic<int> hardware_shaders{0}, set_hardware_shaders{-1};
inline std::atomic<int> async_shaders{0}, set_async_shaders{-1};
inline std::atomic<int> textures{0}, set_textures{-1};
inline std::atomic<bool> open_textures{false};
// Frontend signals after the shader/loading screen has faded away.
inline std::atomic<bool> startup_hint_requested{false};
// Native CFG language IDs; requests are applied on the emulation thread.
inline std::atomic<int> game_language{1}, set_game_language{-1};
inline std::atomic<int> game_language_status{0}; // 0 idle, 1 pending, 2 saved, 3 failed
// Which CFG language IDs the installed deck can actually render. Setup records
// the title and text language in user/setup/ready.json; the boot path stores
// the derived profile before any settings UI or menu reads it.
// 0: USA (English/French/Spanish). 1: Europe built-in text (five languages).
// 2: Europe with the Russian text pack installed: the pack replaces the
// Europe-English assets, so English mode displays Russian.
enum LanguageProfile { UsLanguages = 0, EurStockLanguages = 1, EurRussianLanguages = 2 };
inline std::atomic<int> language_profile{UsLanguages};
inline bool SupportedLanguage(int value, int profile) {
    switch (profile) {
    case EurStockLanguages:
    case EurRussianLanguages:
        return value >= 1 && value <= 5; // English/French/German/Italian/Spanish.
    default:
        return value == 1 || value == 2 || value == 5;
    }
}
inline bool SupportedLanguage(int value) {
    return SupportedLanguage(value, language_profile.load());
}
inline std::atomic<bool> fullscreen_shortcut{false}, textures_shortcut{false};
inline std::atomic<bool> mod_setup_requested{false};
inline std::atomic<bool> controls{false}, fullscreen{false}, quit{false}, about{false};
}
