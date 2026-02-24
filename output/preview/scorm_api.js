/* ===================================================================
   SCORM 1.2 API Wrapper — scorm_api.js
   Обёртка для взаимодействия с LMS через SCORM 1.2 API
   =================================================================== */

var SCORM = (function () {
    "use strict";

    var api = null;
    var initialized = false;
    var finished = false;

    // ------------------------------------------------------------------
    // Поиск API LMS
    // ------------------------------------------------------------------
    function findAPI(win) {
        var attempts = 0;
        while (win && !win.API && attempts < 10) {
            if (win.parent && win.parent !== win) {
                win = win.parent;
            } else if (win.opener) {
                win = win.opener;
            } else {
                break;
            }
            attempts++;
        }
        return win ? win.API || null : null;
    }

    function getAPI() {
        if (api) return api;
        api = findAPI(window);
        if (!api && window.opener) {
            api = findAPI(window.opener);
        }
        if (!api && window.parent) {
            api = findAPI(window.parent);
        }
        return api;
    }

    // ------------------------------------------------------------------
    // Публичные методы
    // ------------------------------------------------------------------
    return {
        /**
         * Инициализация SCORM-сессии.
         */
        initialize: function () {
            if (initialized) return true;
            var lmsAPI = getAPI();
            if (lmsAPI) {
                var result = lmsAPI.LMSInitialize("");
                initialized = result === "true" || result === true;
                if (initialized) {
                    console.log("[SCORM] LMSInitialize — OK");
                }
            } else {
                console.warn("[SCORM] LMS API не найден — автономный режим");
                initialized = true;
            }
            return initialized;
        },

        /**
         * Завершение SCORM-сессии.
         */
        finish: function () {
            if (finished || !initialized) return;
            this.commit();
            var lmsAPI = getAPI();
            if (lmsAPI) {
                lmsAPI.LMSFinish("");
                console.log("[SCORM] LMSFinish — OK");
            }
            finished = true;
        },

        /**
         * Сохранение данных в LMS.
         */
        commit: function () {
            var lmsAPI = getAPI();
            if (lmsAPI) {
                lmsAPI.LMSCommit("");
            }
        },

        /**
         * Установка значения CMI-элемента.
         */
        setValue: function (element, value) {
            var lmsAPI = getAPI();
            if (lmsAPI) {
                lmsAPI.LMSSetValue(element, String(value));
            }
        },

        /**
         * Получение значения CMI-элемента.
         */
        getValue: function (element) {
            var lmsAPI = getAPI();
            if (lmsAPI) {
                return lmsAPI.LMSGetValue(element);
            }
            return "";
        },

        /**
         * Установка статуса прохождения: "completed", "incomplete", "not attempted".
         */
        setLessonStatus: function (status) {
            this.setValue("cmi.core.lesson_status", status);
        },

        /**
         * Установка оценки (0-100).
         */
        setScore: function (score, max, min) {
            max = max || 100;
            min = min || 0;
            this.setValue("cmi.core.score.raw", score);
            this.setValue("cmi.core.score.max", max);
            this.setValue("cmi.core.score.min", min);
        },

        /**
         * Установка местоположения (закладка).
         */
        setLocation: function (location) {
            this.setValue("cmi.core.lesson_location", location);
        },

        /**
         * Получение местоположения (закладка).
         */
        getLocation: function () {
            return this.getValue("cmi.core.lesson_location");
        },

        /**
         * Сохранение suspend_data (произвольные данные).
         */
        setSuspendData: function (data) {
            this.setValue("cmi.suspend_data", typeof data === "string" ? data : JSON.stringify(data));
        },

        /**
         * Получение suspend_data.
         */
        getSuspendData: function () {
            var raw = this.getValue("cmi.suspend_data");
            try {
                return JSON.parse(raw);
            } catch (e) {
                return raw;
            }
        },

        /**
         * Проверка: инициализирован ли SCORM.
         */
        isInitialized: function () {
            return initialized;
        }
    };
})();
