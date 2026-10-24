/* The pointer sensor of the board's drag (dnd-kit). A mouse or pen arms past 5 px as the crow flies (P-02/M1: exactly
   5 px stays a click) or after a 250 ms hold; a touch arms only after a 250 ms hold within 5 px, and a move before that
   lets the press go. A press starts through the card it lands on (`data.current.press`), which says whether it may. */
import { PointerSensor, type DraggableSyntheticListeners, type PointerSensorProps } from '@dnd-kit/core'
import type { PointerEvent as ReactPointerEvent, PointerEventHandler } from 'react'
import { DESKTOP_HOLD_MS, DRAG_THRESHOLD_PX, TOUCH_HOLD_MS, TOUCH_HOLD_TOLERANCE_PX } from './drag'

/** What a draggable card hands the sensor: its own press, true when the press may become a drag. */
export interface CardDragData {
  press: (event: PointerEvent) => boolean
}

export class CardSensor extends PointerSensor {
  constructor(props: PointerSensorProps) {
    const touch = (props.event as PointerEvent).pointerType === 'touch'
    super({
      ...props,
      options: {
        ...props.options,
        activationConstraint: touch
          ? { delay: TOUCH_HOLD_MS, tolerance: TOUCH_HOLD_TOLERANCE_PX }
          : { distance: DRAG_THRESHOLD_PX, delay: DESKTOP_HOLD_MS, tolerance: Infinity },
      },
    })
  }

  static activators = [{
    eventName: 'onPointerDown' as const,
    handler: ((({ nativeEvent }: ReactPointerEvent, _options: unknown, { active }: { active: { data: { current?: unknown } } }) => {
      if (!nativeEvent.isPrimary || nativeEvent.button !== 0) return false
      const data = active.data.current as CardDragData | undefined
      return data?.press(nativeEvent) ?? false
    }) as unknown) as (typeof PointerSensor.activators)[number]['handler'],
  }]
}

/** The draggable's press listener, for the element it is drawn on. */
export function pressListener(listeners: DraggableSyntheticListeners): PointerEventHandler<HTMLElement> | undefined {
  return listeners?.onPointerDown as PointerEventHandler<HTMLElement> | undefined
}
