// SPDX-License-Identifier: GPL-2.0-or-later
#include "mm3d/game_language.h"
#include <cstdio>
#include <cstdlib>
#include <initializer_list>

namespace {
enum Language { English = 1, French = 2, Spanish = 5 };
struct Result {
    bool success;
    bool IsSuccess() const { return success; }
};
struct Config {
    Language current = Language::English;
    Language persisted = Language::English;
    bool writable = true;
    bool rejects_language = false;
    int saves = 0;
    Language GetSystemLanguage() const { return current; }
    void SetSystemLanguage(Language language) {
        if (!rejects_language) current = language;
    }
    Result UpdateConfigNANDSavegame() {
        ++saves;
        if (writable) persisted = current;
        return {writable};
    }
    void Restart() { current = persisted; }
};
void Check(bool pass, const char* message) {
    if (!pass) { std::fprintf(stderr, "%s\n", message); std::exit(1); }
}
}
int main() {
    using namespace MM3D::PlayerSettings;
    Config config;
    InitializeGameLanguage(config);
    Check(game_language == 1 && game_language_status == 0, "initialize from CFG");
    ApplyPendingGameLanguage(config);
    Check(config.saves == 0, "idle frames must not write NAND");
    for (int language : {2, 5, 1}) {
        game_language = language;
        game_language_status = 1;
        set_game_language = language;
        ApplyPendingGameLanguage(config);
        Check(set_game_language == -1 && game_language_status == 2,
              "consume selection and report a successful save");
        Check(config.GetSystemLanguage() == language && game_language == language,
              "publish the saved native CFG language");
        config.Restart();
        game_language = 99;
        InitializeGameLanguage(config);
        Check(game_language == language, "selection survives shutdown and restart");
    }
    const int saves = config.saves;
    for (int invalid : {-1, 0, 3, 99}) {
        set_game_language = invalid;
        ApplyPendingGameLanguage(config);
    }
    Check(config.saves == saves, "reject unsupported CFG language IDs");
    config.writable = false;
    set_game_language = 2;
    ApplyPendingGameLanguage(config);
    Check(game_language == 1 && config.GetSystemLanguage() == 1 && game_language_status == 3,
          "failed NAND write restores the previous language and reports failure");
    config.writable = true;
    config.rejects_language = true;
    set_game_language = 5;
    ApplyPendingGameLanguage(config);
    Check(config.saves == saves + 1 && game_language == 1 && game_language_status == 3,
          "region-rejected language must not be reported as saved");
    config.rejects_language = false;
    set_game_language = 5;
    ApplyPendingGameLanguage(config); // Shutdown flush uses the same emulation-thread path.
    config.Restart();
    InitializeGameLanguage(config);
    Check(game_language == 5 && game_language_status == 0,
          "a request immediately before shutdown survives restart");
    Config startup;
    for (int language : {2, 5, 1}) {
        Check(SaveGameLanguage(startup, language), "startup selection failed");
        startup.Restart();
        InitializeGameLanguage(startup);
        Check(game_language == language && set_game_language == -1,
              "startup language did not reach the next game session");
        const int changed_in_game = language == 2 ? 5 : 2;
        set_game_language = changed_in_game;
        ApplyPendingGameLanguage(startup);
        startup.Restart();
        Check(startup.GetSystemLanguage() == changed_in_game,
              "startup would not read a later in-game language selection");
    }
    const int startup_saves = startup.saves;
    Check(!SaveGameLanguage(startup, 99) && startup.saves == startup_saves,
          "startup accepted an unsupported language");
    startup.writable = false;
    const auto previous = startup.current;
    Check(!SaveGameLanguage(startup, 1) && startup.current == previous,
          "startup failure did not retain the saved language");
    // The installed deck's record decides which options every surface lists.
    Check(LanguageProfileFromRecord("{\"title_id\": \"0004000000125500\"}") == UsLanguages,
          "USA record must keep the USA list");
    Check(LanguageProfileFromRecord(
              "{\"title_id\": \"0004000000125600\", \"text_language\": \"rus\"}") ==
              EurRussianLanguages,
          "Europe record with the Russian pack must select the Russian profile");
    Check(LanguageProfileFromRecord(
              "{\"title_id\": \"0004000000125600\", \"text_language\": \"stock\"}") ==
              EurStockLanguages,
          "Europe record without the pack must keep the built-in profile");
    Check(LanguageProfileFromRecord("{\"title_id\": \"0004000000125600\"}") == EurRussianLanguages,
          "Europe record without a text field follows Setup's own default");
    Check(LanguageProfileFromRecord("") == UsLanguages,
          "no record means no installed deck to override");
    Check(ProfileFromRecordFile("no-such-setup/ready.json") == UsLanguages,
          "missing record file keeps the USA list");
    int count = 0;
    Check(LanguageValuesFor(UsLanguages, count)[2] == 5 && count == 3, "USA option table");
    Check(LanguageValuesFor(EurRussianLanguages, count)[2] == 3 &&
              LanguageValuesFor(EurStockLanguages, count)[4] == 4 && count == 5,
          "Europe option table offers all five renderable CFG ids");
    language_profile.store(EurRussianLanguages);
    Check(SupportedLanguage(3) && !SupportedLanguage(6), "EUR profile accepts its five CFG ids");
    Config rus;
    rus.current = static_cast<Language>(2); // Stale French from an earlier Europe run.
    InitializeGameLanguage(rus);
    Check(set_game_language.load() == 1 && game_language_status.load() == 1,
          "a Russian deck queues English mode at boot");
    ApplyPendingGameLanguage(rus);
    Check(rus.current == English && game_language.load() == 1 && game_language_status.load() == 2,
          "a Russian deck repairs its language to English mode once");
    language_profile.store(UsLanguages);
    std::puts("Game language persistence and failure recovery checks passed.");
}
