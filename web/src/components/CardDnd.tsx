/* The board's drag on dnd-kit: its sensor takes a press on a card (lib/dndSensor.ts) and arms it, and its events drive the
   store's drag (lib/dragActions.ts); where the goal would land is the board's own reading of what is under the pointer
   (lib/drag.ts). dnd-kit scrolls what the card is in when the pointer nears its edge.

   A card hands its press over with `pressToDrag` from its own native listener; one draggable here takes every press, so no
   card listens to dnd-kit's context and none draws again when a drag starts or ends (the board draws in its own order). */
import { DndContext, useDraggable, useSensor, useSensors, type CollisionDetection } from '@dnd-kit/core'
import { useEffect, useRef, type ReactNode } from 'react'
import { recaptureRowRects } from '../lib/drag'
import { CardSensor, pressListener, type CardDragData } from '../lib/dndSensor'
import { store } from '../store'

let handOver: ((event: PointerEvent, press: CardDragData['press']) => void) | null = null

/** A press on a card, which may become its drag: `press` says whether it may, and readies the store. */
export function pressToDrag(event: PointerEvent, press: CardDragData['press']): void {
  handOver?.(event, press)
}

/** The one draggable every press goes through. */
function PressTaker(): ReactNode {
  const data = useRef<CardDragData>({ press: () => false })
  const { listeners, setNodeRef } = useDraggable({ id: 'card', data: data.current })
  useEffect(() => {
    handOver = (event, press) => {
      data.current.press = press
      pressListener(listeners)?.({ nativeEvent: event } as never)
    }
    return () => {
      handOver = null
    }
  }, [listeners])
  return <div ref={setNodeRef} hidden />
}

/** Where the pointer is: dnd-kit hands it to collision detection on every move and every scroll. */
let pointer: { x: number; y: number } | null = null
const followPointer: CollisionDetection = ({ pointerCoordinates }) => {
  if (pointerCoordinates) pointer = { x: pointerCoordinates.x, y: pointerCoordinates.y }
  return []
}

const silent = {
  onDragStart: () => undefined,
  onDragMove: () => undefined,
  onDragOver: () => undefined,
  onDragEnd: () => undefined,
  onDragCancel: () => undefined,
}

/** The rows were read at the press: a scroll under the hand moves them, so they are read again. */
function onScroll(): void {
  if (store.state.drag.id) recaptureRowRects()
}

/** A card row lets touch scroll (goalCard.css), so a swipe over cards still turns the board. Once a hold has picked
    a card up, the finger belongs to the card: the browser must not start a scroll, which would cancel the drag. */
function onTouchMove(event: TouchEvent): void {
  if (store.state.drag.id && event.cancelable) event.preventDefault()
}

export function CardDnd({ children }: { children: ReactNode }): ReactNode {
  const sensors = useSensors(useSensor(CardSensor))
  useEffect(() => {
    document.addEventListener('scroll', onScroll, true)
    document.addEventListener('touchmove', onTouchMove, { passive: false })
    return () => {
      document.removeEventListener('scroll', onScroll, true)
      document.removeEventListener('touchmove', onTouchMove)
    }
  }, [])
  return (
    <DndContext
      sensors={sensors}
      collisionDetection={followPointer}
      // Focus left with the press (the armed drag blurs it, P-02) and is not brought back to the card.
      accessibility={{ announcements: silent, screenReaderInstructions: { draggable: '' }, restoreFocus: false }}
      onDragPending={({ initialCoordinates, offset }) => {
        pointer = { x: initialCoordinates.x - (offset?.x ?? 0), y: initialCoordinates.y - (offset?.y ?? 0) }
        store.pointerMoveDrag(pointer.x, pointer.y)
      }}
      onDragStart={() => store.armDrag()}
      onDragMove={() => {
        if (pointer) store.pointerMoveDrag(pointer.x, pointer.y)
      }}
      onDragEnd={() => {
        if (pointer) store.pointerMoveDrag(pointer.x, pointer.y)
        store.pointerUpDrag()
      }}
      onDragCancel={() => store.pointerUpDrag(true)}
      onDragAbort={() => store.pointerUpDrag()}
    >
      <PressTaker />
      {children}
    </DndContext>
  )
}
