import json
import asyncio
from typing import Optional, List, Tuple, Dict, Any
from config import YANDEX_GEO_KEY
from utils.logger import logger
from services.http_client import http_client


class YandexGeoService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://geocode-maps.yandex.ru/1.x/"

    async def _request(self, params: Dict[str, Any]) -> Optional[Dict]:
        """Внутренний метод для выполнения запроса к API"""
        params['apikey'] = self.api_key
        params['format'] = 'json'

        response = await http_client.get(self.base_url, params=params, timeout=10.0)

        if response is not None:
            if response.status_code == 200:
                try:
                    return response.json()
                except (ValueError, TypeError) as exc:
                    await logger.log(
                        "Yandex Geo API returned invalid JSON: "
                        f"{type(exc).__name__}"
                    )
            else:
                await logger.log(f"Yandex Geo API status error: {response.status_code}")

        return None

    def _get_postcode(self, geo_object: Dict) -> Optional[str]:
        """Вспомогательный метод для извлечения индекса (Postal Code)"""
        try:
            addr = geo_object['GeoObject']['metaDataProperty']['GeocoderMetaData']['Address']
            return addr.get('postal_code')
        except (KeyError, TypeError):
            return None

    async def get_full_address_data(self, lon: float, lat: float,) -> str:
        """
        Получает полные данные об адресе по координатам.
        Возвращает JSON-строку.
        """
        result_dict = {"longitude": float(lon), "latitude": float(lat)}

        params = {
            "kind": "house",
            "results": 1,
            "geocode": f"{lon} {lat}"
        }

        data = await self._request(params)

        if not data:
            return json.dumps(result_dict, ensure_ascii=False)

        try:
            feature_member = data['response']['GeoObjectCollection']['featureMember']
            if not feature_member:
                return json.dumps(result_dict, ensure_ascii=False)

            address_object = feature_member[0]
            address_data = address_object["GeoObject"]['metaDataProperty']['GeocoderMetaData']['Address']

            result_dict['formatted'] = address_data['formatted']

            for component in address_data.get('Components', []):
                # kind (например, 'country', 'locality') становится ключом
                result_dict[component['kind']] = component['name']
            postal_code = self._get_postcode(address_object)
            if postal_code:
                result_dict['postal_code'] = postal_code

        except (KeyError, IndexError) as e:
            await logger.log(f"Error parsing full address data: {e}")

        return json.dumps(result_dict, ensure_ascii=False)

    async def search_places(self, query: str, lang: str) -> List[Tuple[str, str, Optional[str]]]:
        """
        Ищет адреса по текстовому запросу.
        Возвращает список кортежей: (Адрес, "lon lat", Индекс)
        """
        params = {
            "lang": f"{lang}_RU",
            "results": 5,
            "geocode": query
        }

        data = await self._request(params)
        addresses = []

        if not data:
            return addresses

        try:
            feature_members = data['response']['GeoObjectCollection']['featureMember']
            for item in feature_members:
                geo_object = item['GeoObject']
                meta = geo_object['metaDataProperty']['GeocoderMetaData']

                # Нужны только полные адреса с номерами дома
                if meta.get('kind') == 'house':
                    text_address = meta['text']
                    pos = geo_object['Point']['pos']  # Строка "lon lat"
                    postal_code = self._get_postcode(item)

                    addresses.append((text_address, pos, postal_code))

        except (KeyError, IndexError) as e:
            await logger.log(f"Error parsing search results: {e}")

        return addresses

    async def get_formatted_address(self, lon: float, lat: float, lang: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Возвращает (Форматированный адрес, Индекс) по координатам.
        """
        params = {
            "lang": f"{lang}_RU",
            "kind": "house",
            "results": 1,
            "geocode": f"{lon} {lat}"
        }

        data = await self._request(params)
        if not data:
            return None, None

        try:
            feature_member = data['response']['GeoObjectCollection']['featureMember']
            if not feature_member:
                return None, None

            first_obj = feature_member[0]
            formatted_addr = first_obj["GeoObject"]['metaDataProperty']['GeocoderMetaData']['Address']['formatted']
            postal_code = self._get_postcode(first_obj)

            return formatted_addr, postal_code

        except (KeyError, IndexError) as e:
            await logger.log(f"Error parsing formatted address: {e}")
            return None, None

geo_service = YandexGeoService(api_key=YANDEX_GEO_KEY)
