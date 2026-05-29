import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import vi from "./vi.json";
import en from "./en.json";

i18n.use(initReactI18next).init({
  resources: { vi_VN: { translation: vi }, en_US: { translation: en } },
  lng: "vi_VN",
  fallbackLng: "en_US",
  interpolation: { escapeValue: false },
});

export default i18n;
