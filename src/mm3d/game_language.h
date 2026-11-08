// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <string>
#include "mm3d/player_settings.h"
#include "mm3d/title_ids.h"

namespace MM3D::PlayerSettings {
// While emulation is running, CFG is owned by the emulation thread.
// Setup writes user/setup/ready.json with title_id and text_language; both
// desktop and Android keep the user path pointed at the installed deck, so
// this parser runs identically on every platform without a JSON dependency.
inline std::string QuotedTitleId(std::uint64_t id) {
    char text[19];
    std::snprintf(text, sizeof text, "\"%016llx\"", static_cast<unsigned long long>(id));
    return std::string(text);
}
inline int LanguageProfileFromRecord(const std::string& record) {
    const std::string eur_id = QuotedTitleId(MajoraMask3DEurTitle);
    const auto value_after = [&record](const char* key, const std::string& wanted) {
        const auto at = record.find(key);
        if (at == std::string::npos) return false;
        const auto found = record.find(wanted, at);
        return found != std::string::npos && found < at + 80; // never past the next field
    };
    if (!value_after("\"title_id\"", eur_id)) return UsLanguages;
    // No record text language: Setup's own default for Europe is Russian, and
    // Android installs predating the record were made through that default
    // prompt. Desktop ready.json without the field predates language
    // switching entirely, so its built-in text stays.
    return value_after("\"text_language\"", "\"rus\"") ? EurRussianLanguages : EurStockLanguages;
}
// CFG language ids for a profile, in the order the UI lists them:
// English, French, German, Spanish, Italian (CFG ids 1,2,3,5,4 - 4 is Italian).
inline const int* LanguageValuesFor(int profile, int& count) {
    static constexpr int us[] = {1, 2, 5};
    static constexpr int eur[] = {1, 2, 3, 5, 4};
    if (profile == EurStockLanguages || profile == EurRussianLanguages) {
        count = 5;
        return eur;
    }
    count = 3;
    return us;
}
// Read the deck record at the given setup/ready.json path. A missing file
// leaves the USA list: no deck is installed to override it.
inline int ProfileFromRecordFile(const std::string& ready_path) {
    std::ifstream file(ready_path, std::ios::binary);
    if (!file) return UsLanguages;
    const std::string record((std::istreambuf_iterator<char>(file)),
                             std::istreambuf_iterator<char>());
    return LanguageProfileFromRecord(record);
}

template<class Config>
void InitializeGameLanguage(Config& config) {
    game_language.store(config.GetSystemLanguage());
    game_language_status.store(0);
    set_game_language.store(-1);
    // A Russian deck renders its text pack only through the Europe-English
    // assets. A stale European language in the NAND would silently show the
    // untouched original instead; queue the English-mode id so the existing
    // per-frame apply path repairs the setting once.
    if (language_profile.load() == EurRussianLanguages && game_language.load() != 1) {
        set_game_language.store(1);
        game_language_status.store(1);
    }
}

// Startup and in-game selections use the same validated NAND transaction.
template<class Config>
bool SaveGameLanguage(Config& config, int requested) {
    if (!SupportedLanguage(requested)) return false;
    const auto previous = config.GetSystemLanguage();
    using Language = decltype(config.GetSystemLanguage());
    config.SetSystemLanguage(static_cast<Language>(requested));
    if (config.GetSystemLanguage() != requested) {
        config.SetSystemLanguage(previous);
        game_language.store(previous);
        game_language_status.store(3);
        return false;
    }
    const bool saved = config.UpdateConfigNANDSavegame().IsSuccess();
    if (!saved) config.SetSystemLanguage(previous);
    game_language.store(config.GetSystemLanguage());
    game_language_status.store(saved ? 2 : 3);
    return saved;
}

template<class Config>
void ApplyPendingGameLanguage(Config& config) {
    const int requested = set_game_language.exchange(-1);
    if (SupportedLanguage(requested)) SaveGameLanguage(config, requested);
}
} // namespace MM3D::PlayerSettings
