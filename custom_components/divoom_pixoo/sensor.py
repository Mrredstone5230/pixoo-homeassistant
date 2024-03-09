import asyncio
import logging
from datetime import timedelta

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.template import Template, TemplateError

from .const import DOMAIN, VERSION
from .pages.solar import solar
from .pages.fuel import fuel
from .pixoo64._font import FONT_PICO_8, FONT_GICKO, FIVE_PIX, ELEVEN_PIX

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry: ConfigEntry, async_add_entities):
    async_add_entities([ Pixoo64(config_entry=config_entry, pixoo=hass.data[DOMAIN][config_entry.entry_id]["pixoo"]) ], True)
    platform = entity_platform.current_platform.get()
    platform.async_register_entity_service(
        'show_message',
        {
            vol.Required('messages'): [cv.string],
            vol.Required('positions'): [[cv.positive_int]],
            vol.Required('colors'): [[cv.positive_int]],
            vol.Required('fonts'): [cv.string],
            vol.Optional('images', default=[]): [cv.string],
            vol.Optional('image_positions', default=[]): [[cv.positive_int]],
            vol.Optional('info_text', default="No"): cv.string,
            vol.Optional('info_images', default="No"): cv.string,
        },
        'async_show_message',
    )


class Pixoo64(Entity):

    def __init__(self, pages="", scan_interval=timedelta(seconds=15), pixoo=None, config_entry=None):
        # self._ip_address = ip_address
        self._pixoo = pixoo
        self._config_entry = config_entry
        self._pages = self._config_entry.options.get('pages_data', pages)
        self._scan_interval = timedelta(seconds=int(self._config_entry.options.get('scan_interval', scan_interval)))
        self._current_page_index = 0
        self._current_page = self._pages[self._current_page_index]
        self._attr_has_entity_name = True
        self._attr_name = 'Current Page'
        self._attr_extra_state_attributes = {}
        self._attr_extra_state_attributes['page'] = self._current_page['page']
        _LOGGER.debug("All pages for %s: %s", self._pixoo.address, self._pages)
        self.showing_notification = False

    async def async_added_to_hass(self):
        if DOMAIN in self.hass.data:
            self.hass.data[DOMAIN].setdefault('entities', []).append(self)
        self._update_interval = async_track_time_interval(
            self.hass,
            self._async_update,
            self._scan_interval
        )
        await self._async_update()

    async def async_will_remove_from_hass(self):
        """When entity is being removed from hass."""
        if self._update_interval is not None:
            self._update_interval()
            self._update_interval = None

    async def _async_update(self, now=None):
        _LOGGER.debug("Update called at %s for %s", now, self._pixoo.address)
        await self._async_update_data()

    async def _async_update_data(self):
        if self.showing_notification:
            return

        def update():
            pixoo = self._pixoo
            pixoo.clear()

            if "channel" in self.page:
                for ch in self.page["channel"]:
                    pixoo.set_custom_page(ch['number'])

            if "clockId" in self.page:
                for clock in self.page["clockId"]:
                    pixoo.set_clock(clock['number'])

            if "images" in self.page:
                for image in self.page["images"]:
                    pixoo.draw_image(image['image'], tuple(image['position']))

            if "texts" in self.page:
                for text in self.page["texts"]:
                    text_template = Template(text['text'], self.hass)
                    try:
                        rendered_text = str(text_template.async_render())
                    except TemplateError as e:
                        _LOGGER.error("Template render error: %s", e)
                        rendered_text = "Template Error"

                    if text['font'] == "FONT_PICO_8":
                        pixoo.draw_text(rendered_text, tuple(text['position']), tuple(text['font_color']), FONT_PICO_8)
                    if text['font'] == "FONT_GICKO":
                        pixoo.draw_text(rendered_text.upper(), tuple(text['position']), tuple(text['font_color']),
                                        FONT_GICKO)
                    if text['font'] == "FIVE_PIX":
                        pixoo.draw_text(rendered_text.upper(), tuple(text['position']), tuple(text['font_color']), FIVE_PIX)

            if "PV" in self.page:
                solar(pixoo, self.hass, self.page, FONT_PICO_8, FONT_GICKO)

            if "Fuel" in self.page:
                _LOGGER.info(f"Fuel = {self.page}")
                _LOGGER.info(f"Fuel = {self.page['Fuel']}")
                fuel(pixoo, self.hass, self.page, FONT_PICO_8, FONT_GICKO, FIVE_PIX, ELEVEN_PIX)

            if "channel" not in self.page and "clockId" not in self.page:
                pixoo.push()

        page_displayed = False

        while not page_displayed:
            self.page = self._pages[self._current_page_index]
            self.schedule_update_ha_state()

            try:
                is_enabled = str(Template(self.page['enable'], self.hass).async_render())
                is_enabled = is_enabled.lower() in ['true', 'yes', '1', 'on']
                _LOGGER.info(f"Template? = {self.page['enable']}")
            except TemplateError as e:
                _LOGGER.error(f"Error rendering enable template: {e}")
                is_enabled = False

            if is_enabled:
                _LOGGER.info(f"Yes it is True!")
                await self.hass.async_add_executor_job(update)
                self._current_page_index = (self._current_page_index + 1) % len(self._pages)
                page_displayed = True
            else:
                _LOGGER.info(f"No it is False!")
                self._current_page_index = (self._current_page_index + 1) % len(self._pages)
                if self.page == initial_index:
                    break

    async def async_show_message(self, messages, positions, colors, fonts, images=None, image_positions=None, info_text=None, info_images=None):
        if not all([messages, positions, colors, fonts]) or len(messages) != len(positions) != len(colors) != len(fonts):
            _LOGGER.error("Lists for messages, positions, colors, and fonts must all be present and have the same length.")
            return

        self.showing_notification = True

        def draw():
            pixoo = self._pixoo
            pixoo.clear()
            _LOGGER.debug("Service called for %s (%s)", self._config_entry.title, self._pixoo.address)

            for img, img_pos in zip(images, image_positions):
                pixoo.draw_image(img, tuple(img_pos))

            for message, position, color, font in zip(messages, positions, colors, fonts):
                selected_font = FONT_PICO_8 if font == 'FONT_PICO_8' else FONT_GICKO
                if font == 'FONT_PICO_8':
                    pixoo.draw_text(message, tuple(position), tuple(color), selected_font)
                else:
                    pixoo.draw_text(message.upper(), tuple(position), tuple(color), selected_font)

            pixoo.push()

        await self.hass.async_add_executor_job(draw)
        await asyncio.sleep(self._scan_interval.total_seconds())
        self.showing_notification = False

    @property
    def state(self):
        return self._current_page['page']

    @property
    def entity_category(self):
        return EntityCategory.DIAGNOSTIC


    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._config_entry.entry_id)) if self._config_entry is not None else (DOMAIN, "divoom")},
            name=self._config_entry.title,
            manufacturer="Divoom",
            model="Pixoo",
            sw_version=VERSION,
        )

    @property
    def unique_id(self):
        return "current_page_" + str(self._config_entry.entry_id)
